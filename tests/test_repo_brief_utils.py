import json
import logging
from types import SimpleNamespace

import pytest
import requests

from repo_brief import __version__, cli, github_client
from repo_brief import agents_workflow as workflow
from repo_brief.budget import Pricing, validate_price_overrides
from repo_brief.github_client import parse_github_repo_url, truncate


def test_parse_github_repo_url_accepts_valid_https_url() -> None:
    owner, repo = parse_github_repo_url("https://github.com/openai/openai-python")
    assert owner == "openai"
    assert repo == "openai-python"


@pytest.mark.parametrize(
    "bad_url",
    [
        "git@github.com:openai/openai-python.git",
        "github.com/openai/openai-python",
        "https://gitlab.com/openai/openai-python",
    ],
)
def test_parse_github_repo_url_rejects_invalid_url(bad_url: str) -> None:
    with pytest.raises(ValueError):
        parse_github_repo_url(bad_url)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"briefing_markdown": "raw", "files_to_inspect": ["a.py"]}', "raw"),
        (
            '```json\n{"briefing_markdown": "fenced", "files_to_inspect": ["b.py"]}\n```',
            "fenced",
        ),
        (
            'Preface\n{"briefing_markdown": "embedded", "files_to_inspect": ["c.py"]}\nPostscript',
            "embedded",
        ),
    ],
)
def test_json_or_fallback_parses_structured_json(text: str, expected: str) -> None:
    out = workflow.json_or_fallback(text)
    assert out["briefing_markdown"] == expected


def test_json_fallback_uses_fallback_key_for_invalid_json() -> None:
    text = 'not valid {"briefing_markdown": invalid } text'
    out = workflow.json_or_fallback(text, fallback_key="reading_plan_markdown")
    assert out["reading_plan_markdown"] == text
    assert out["files_to_inspect"] == []


def test_truncate_shortens_long_strings() -> None:
    text = "x" * 60
    truncated = truncate(text, max_chars=30)
    assert truncated.endswith("...[truncated]...")


def test_truncate_handles_non_positive_limit() -> None:
    assert truncate("abcdef", max_chars=0) == ""
    assert truncate("abcdef", max_chars=-1) == ""


def test_tree_summary_uses_type_prefixes_and_stable_ordering() -> None:
    paths = [
        "  src/",
        "README.md",
        "src/main.py  ",
        " docs/",
        "docs/index.rst",
    ]

    summary = github_client.tree_summary(paths, max_entries=5)

    assert summary.splitlines() == [
        "[FILE] README.md",
        "[DIR] docs/",
        "[FILE] docs/index.rst",
        "[DIR] src/",
        "[FILE] src/main.py",
    ]


def test_pick_key_files_includes_top_level_conventional_files_and_respects_max() -> None:
    tree_index = {
        "README.md": "blob",
        "CONTRIBUTING.md": "blob",
        "LICENSE": "blob",
        "pyproject.toml": "blob",
        "src/main.py": "blob",
        "docs/": "tree",
    }

    selected = github_client.pick_key_files(tree_index, max_files=3)

    assert selected == ["README.md", "CONTRIBUTING.md", "LICENSE"]


def test_validate_price_overrides_requires_both_values() -> None:
    with pytest.raises(ValueError):
        validate_price_overrides(price_in=1.0, price_out=None)


def test_cli_version_flag_prints_version_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["repo-brief", "--version"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert captured.out.strip() == __version__


def test_cli_exits_with_code_2_when_openai_api_key_missing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["repo-brief", "https://github.com/openai/openai-python"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 2
    assert "OPENAI_API_KEY is required" in caplog.text


def test_safe_get_json_raises_runtime_error_for_non_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 200
        headers: dict[str, str] = {}
        text = "<!doctype html><html>oops</html>"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            raise json.JSONDecodeError("bad", self.text, 0)

    monkeypatch.setattr(
        github_client.requests.Session, "get", lambda _self, *_args, **_kwargs: Response()
    )

    with pytest.raises(RuntimeError) as exc_info:
        github_client.safe_get_json("https://api.github.com/repos/openai/openai-python")

    message = str(exc_info.value)
    assert "status 200" in message
    assert "https://api.github.com/repos/openai/openai-python" in message
    assert "Body snippet" in message


class _DummyResult:
    def __init__(self, payload: dict[str, str]) -> None:
        self.final_output = json.dumps(payload)


def test_run_briefing_loop_fetches_repo_context_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_repo_context(repo_url: str, **_kwargs: object) -> dict[str, object]:
        calls["count"] += 1
        return {
            "tree_summary": "📄 README.md",
            "key_files": ["README.md"],
        }

    def fake_run_sync(
        agent: object,
        prompt: str,
        max_turns: int,
        run_config: object,
    ) -> _DummyResult:
        del prompt, max_turns, run_config
        if agent is workflow.OverviewAgent:
            return _DummyResult({"briefing_markdown": "brief", "files_to_inspect": []})
        return _DummyResult({"reading_plan_markdown": "plan"})

    monkeypatch.setattr(workflow, "fetch_repo_context_impl", fake_repo_context)
    monkeypatch.setattr(workflow.Runner, "run_sync", fake_run_sync)
    monkeypatch.setattr(
        workflow, "usage_totals", lambda _result: {"total_tokens": 0, "requests": 1}
    )
    monkeypatch.setattr(workflow, "estimate_cost_usd", lambda _result, _pricing: 0.0)

    workflow.run_briefing_loop(
        repo_url="https://github.com/openai/openai-python",
        model="gpt-4.1-mini",
        max_iters=2,
        max_turns=1,
        max_cost=0.0,
        max_tokens=0,
        pricing=SimpleNamespace(in_per_1m=0.0, out_per_1m=0.0, cached_in_per_1m=0.0),
    )

    assert calls["count"] == 1


def test_run_briefing_loop_passes_ref_to_repo_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_repo_context(repo_url: str, **kwargs: object) -> dict[str, object]:
        del repo_url
        captured.update(kwargs)
        return {
            "tree_summary": "📄 README.md",
            "key_files": ["README.md"],
            "default_branch": "main",
            "ref": kwargs.get("ref", ""),
        }

    def fake_run_sync(
        agent: object,
        prompt: str,
        max_turns: int,
        run_config: object,
    ) -> _DummyResult:
        del prompt, max_turns, run_config
        if agent is workflow.OverviewAgent:
            return _DummyResult({"briefing_markdown": "brief", "files_to_inspect": []})
        return _DummyResult({"reading_plan_markdown": "plan"})

    monkeypatch.setattr(workflow, "fetch_repo_context_impl", fake_repo_context)
    monkeypatch.setattr(workflow.Runner, "run_sync", fake_run_sync)
    monkeypatch.setattr(
        workflow, "usage_totals", lambda _result: {"total_tokens": 0, "requests": 1}
    )
    monkeypatch.setattr(workflow, "estimate_cost_usd", lambda _result, _pricing: 0.0)

    workflow.run_briefing_loop(
        repo_url="https://github.com/openai/openai-python",
        model="gpt-4.1-mini",
        max_iters=1,
        max_turns=1,
        max_cost=0.0,
        max_tokens=0,
        pricing=SimpleNamespace(in_per_1m=0.0, out_per_1m=0.0, cached_in_per_1m=0.0),
        ref="release/v1",
    )

    assert captured["ref"] == "release/v1"


def test_gh_headers_reads_github_token_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert "Authorization" not in github_client.gh_headers()

    monkeypatch.setenv("GITHUB_TOKEN", "new-token")
    headers = github_client.gh_headers()

    assert headers["Authorization"] == "Bearer new-token"


def test_pricing_for_model_reads_env_prices_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRICE_IN_PER_1M", "9.5")
    monkeypatch.setenv("PRICE_OUT_PER_1M", "10.5")
    monkeypatch.setenv("PRICE_CACHED_IN_PER_1M", "1.5")

    pricing = Pricing.for_model(
        model="gpt-4.1-mini",
        price_in=None,
        price_out=None,
        price_cached_in=None,
    )

    assert pricing.in_per_1m == 9.5
    assert pricing.out_per_1m == 10.5
    assert pricing.cached_in_per_1m == 1.5


def test_run_briefing_loop_passes_model_via_run_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_config_models: list[str | None] = []

    def fake_repo_context(repo_url: str, **_kwargs: object) -> dict[str, object]:
        del repo_url
        return {"tree_summary": "📄 README.md", "key_files": ["README.md"]}

    def fake_run_sync(
        agent: object,
        prompt: str,
        max_turns: int,
        run_config: object,
    ) -> _DummyResult:
        del prompt, max_turns
        run_config_models.append(getattr(run_config, "model", None))
        if agent is workflow.OverviewAgent:
            return _DummyResult({"briefing_markdown": "brief", "files_to_inspect": []})
        return _DummyResult({"reading_plan_markdown": "plan"})

    monkeypatch.setattr(workflow, "fetch_repo_context_impl", fake_repo_context)
    monkeypatch.setattr(workflow.Runner, "run_sync", fake_run_sync)
    monkeypatch.setattr(
        workflow, "usage_totals", lambda _result: {"total_tokens": 0, "requests": 1}
    )
    monkeypatch.setattr(workflow, "estimate_cost_usd", lambda _result, _pricing: 0.0)

    workflow.run_briefing_loop(
        repo_url="https://github.com/openai/openai-python",
        model="gpt-4.1",
        max_iters=1,
        max_turns=1,
        max_cost=0.0,
        max_tokens=0,
        pricing=SimpleNamespace(in_per_1m=0.0, out_per_1m=0.0, cached_in_per_1m=0.0),
    )

    assert run_config_models == ["gpt-4.1", "gpt-4.1"]


def test_safe_get_json_retries_transient_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    class Response:
        def __init__(self, status_code: int, payload: dict[str, object]) -> None:
            self.status_code = status_code
            self._payload = payload
            self.headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise requests.HTTPError("bad gateway", response=self)

        def json(self) -> dict[str, object]:
            return self._payload

    def fake_get(_self: object, url: str, headers: dict[str, str], timeout: int) -> Response:
        del _self, url, headers, timeout
        calls["count"] += 1
        if calls["count"] < 3:
            return Response(502, {})
        return Response(200, {"ok": True})

    monkeypatch.setattr(github_client.requests.Session, "get", fake_get)
    monkeypatch.setattr(github_client.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(github_client.random, "uniform", lambda _a, _b: 0.0)

    payload = github_client.safe_get_json("https://api.github.com/repos/openai/openai-python")

    assert payload == {"ok": True}
    assert calls["count"] == 3


def test_safe_get_json_uses_retry_after_for_429(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}
    sleeps: list[float] = []

    class Response:
        def __init__(
            self, status_code: int, payload: dict[str, object], retry_after: str | None = None
        ) -> None:
            self.status_code = status_code
            self._payload = payload
            self.headers: dict[str, str] = {}
            if retry_after is not None:
                self.headers["Retry-After"] = retry_after

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise requests.HTTPError("too many requests", response=self)

        def json(self) -> dict[str, object]:
            return self._payload

    def fake_get(_self: object, url: str, headers: dict[str, str], timeout: int) -> Response:
        del _self, url, headers, timeout
        calls["count"] += 1
        if calls["count"] == 1:
            return Response(429, {}, retry_after="7")
        return Response(200, {"ok": True})

    monkeypatch.setattr(github_client.requests.Session, "get", fake_get)
    monkeypatch.setattr(github_client.time, "sleep", lambda seconds: sleeps.append(seconds))

    payload = github_client.safe_get_json("https://api.github.com/repos/openai/openai-python")

    assert payload == {"ok": True}
    assert calls["count"] == 2
    assert sleeps == [7.0]


def test_safe_get_json_raises_clear_error_on_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 403
        headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}

        def raise_for_status(self) -> None:
            raise requests.HTTPError("forbidden", response=self)

        def json(self) -> dict[str, object]:
            return {}

    monkeypatch.setattr(
        github_client.requests.Session, "get", lambda _self, *_args, **_kwargs: Response()
    )

    with pytest.raises(RuntimeError) as exc_info:
        github_client.safe_get_json("https://api.github.com/repos/openai/openai-python")

    message = str(exc_info.value)
    assert "Set GITHUB_TOKEN" in message
    assert "1700000000" in message
    assert "UTC" in message


def test_render_output_mentions_skipped_reading_plan_on_budget_limit() -> None:
    rendered = cli.render_output(
        {
            "briefing_markdown": "brief",
            "reading_plan_markdown": "",
            "usage": {"estimated_cost_usd": 0.0, "total_tokens": 1, "requests": 1},
            "stopped_reason": "budget_exceeded",
        },
        output_format="markdown",
    )

    assert "Reading plan skipped because the configured budget limit was reached." in rendered


def test_cli_passes_context_limit_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_briefing_loop(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "briefing_markdown": "brief",
            "reading_plan_markdown": "",
            "usage": {"estimated_cost_usd": 0.0, "total_tokens": 0, "requests": 1},
            "stopped_reason": "completed",
        }

    monkeypatch.setattr(workflow, "run_briefing_loop", fake_run_briefing_loop)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sys.argv",
        [
            "repo-brief",
            "https://github.com/openai/openai-python",
            "--max-readme-chars",
            "111",
            "--max-tree-entries",
            "222",
            "--max-key-files",
            "9",
            "--max-file-chars",
            "333",
        ],
    )

    cli.main()

    assert captured["max_readme_chars"] == 111
    assert captured["max_tree_entries"] == 222
    assert captured["max_key_files"] == 9
    assert captured["max_file_chars"] == 333


def test_cli_passes_ref_to_run_briefing_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_briefing_loop(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "briefing_markdown": "brief",
            "reading_plan_markdown": "",
            "usage": {"estimated_cost_usd": 0.0, "total_tokens": 0, "requests": 1},
            "stopped_reason": "completed",
        }

    monkeypatch.setattr(workflow, "run_briefing_loop", fake_run_briefing_loop)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sys.argv",
        [
            "repo-brief",
            "https://github.com/openai/openai-python",
            "--ref",
            "release/v1",
        ],
    )

    cli.main()

    assert captured["ref"] == "release/v1"


def test_cli_verbose_writes_diagnostics_to_stderr_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="repo_brief")

    def fake_run_briefing_loop(**kwargs: object) -> dict[str, object]:
        diagnostics = kwargs.get("diagnostics")
        assert callable(diagnostics)
        diagnostics("stage: overview")
        diagnostics("repo context: default_branch=main tree_entries=1 key_files=['README.md']")
        return {
            "briefing_markdown": "brief",
            "reading_plan_markdown": "plan",
            "usage": {"estimated_cost_usd": 0.0, "total_tokens": 0, "requests": 1},
            "stopped_reason": "completed",
            "warnings": [],
        }

    monkeypatch.setattr(workflow, "run_briefing_loop", fake_run_briefing_loop)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sys.argv",
        ["repo-brief", "https://github.com/openai/openai-python", "--verbose"],
    )

    cli.main()

    captured = capsys.readouterr()
    assert "brief" in captured.out
    assert "stage: overview" in caplog.text
    assert "parsed repo: owner=openai, repo=openai-python" in caplog.text


def test_run_briefing_loop_invalid_overview_json_schema_falls_back_with_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_repo_context(repo_url: str, **_kwargs: object) -> dict[str, object]:
        del repo_url
        return {
            "tree_summary": "📄 README.md",
            "key_files": ["README.md"],
            "default_branch": "main",
        }

    def fake_run_sync(
        agent: object,
        prompt: str,
        max_turns: int,
        run_config: object,
    ) -> _DummyResult:
        del prompt, max_turns, run_config
        if agent is workflow.OverviewAgent:
            return _DummyResult({"files_to_inspect": ["README.md"]})
        return _DummyResult({"reading_plan_markdown": "plan"})

    monkeypatch.setattr(workflow, "fetch_repo_context_impl", fake_repo_context)
    monkeypatch.setattr(workflow.Runner, "run_sync", fake_run_sync)
    monkeypatch.setattr(
        workflow, "usage_totals", lambda _result: {"total_tokens": 0, "requests": 1}
    )
    monkeypatch.setattr(workflow, "estimate_cost_usd", lambda _result, _pricing: 0.0)

    result = workflow.run_briefing_loop(
        repo_url="https://github.com/openai/openai-python",
        model="gpt-4.1",
        max_iters=1,
        max_turns=1,
        max_cost=0.0,
        max_tokens=0,
        pricing=SimpleNamespace(in_per_1m=0.0, out_per_1m=0.0, cached_in_per_1m=0.0),
    )

    assert result["briefing_markdown"] == '{"files_to_inspect": ["README.md"]}'
    assert any(
        "overview stage returned invalid JSON schema" in warning for warning in result["warnings"]
    )


def test_fetch_repo_context_impl_uses_provided_ref_without_repo_metadata_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_counter = {"repo_meta": 0}

    def fake_safe_get_json(url: str, **_kwargs: object) -> dict[str, object]:
        if url.endswith("/repos/openai/openai-python"):
            call_counter["repo_meta"] += 1
            return {"default_branch": "main"}
        if "/branches/" in url:
            return {"commit": {"commit": {"tree": {"sha": "tree123"}}}}
        if "/git/trees/tree123" in url:
            return {"tree": [{"path": "README.md", "type": "blob"}]}
        if "/readme" in url:
            return {"content": ""}
        return {"type": "file", "content": ""}

    monkeypatch.setattr(github_client, "safe_get_json", fake_safe_get_json)
    monkeypatch.setattr(
        github_client,
        "fetch_file_content",
        lambda owner,
        repo,
        path,
        ref,
        max_chars,
        session=None: f"{owner}/{repo}:{path}@{ref}:{max_chars}",
    )

    payload = github_client.fetch_repo_context_impl(
        repo_url="https://github.com/openai/openai-python",
        ref="feature/ref-support",
        max_key_files=1,
    )

    assert call_counter["repo_meta"] == 0
    assert payload["ref"] == "feature/ref-support"


def test_fetch_files_impl_uses_provided_default_branch_without_repo_metadata_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_counter = {"repo_meta": 0}

    def fake_safe_get_json(url: str, **_kwargs: object) -> dict[str, object]:
        if url.endswith("/repos/openai/openai-python"):
            call_counter["repo_meta"] += 1
            return {"default_branch": "main"}
        return {"type": "file", "content": ""}

    monkeypatch.setattr(github_client, "safe_get_json", fake_safe_get_json)
    monkeypatch.setattr(
        github_client,
        "fetch_file_content",
        lambda owner,
        repo,
        path,
        ref,
        max_chars,
        session=None: f"{owner}/{repo}:{path}@{ref}:{max_chars}",
    )

    payload = github_client.fetch_files_impl(
        repo_url="https://github.com/openai/openai-python",
        paths=["README.md"],
        max_file_chars=42,
        default_branch="develop",
    )

    assert call_counter["repo_meta"] == 0
    assert payload["default_branch"] == "develop"
    assert payload["files"]["README.md"].endswith("@develop:42")
