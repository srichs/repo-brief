import json
from types import SimpleNamespace

import pytest
import requests

from repo_brief import agents_workflow as workflow
from repo_brief import cli, github_client
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


def test_json_fallback_uses_fallback_key_for_non_json() -> None:
    out = workflow.json_or_fallback("plain text", fallback_key="reading_plan_markdown")
    assert out["reading_plan_markdown"] == "plain text"
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
        "src/",
        "README.md",
        "src/main.py",
        "docs/",
        "docs/index.rst",
    ]

    summary = github_client.tree_summary(paths, max_entries=5)

    assert summary.splitlines() == [
        "📄 README.md",
        "📁 docs/",
        "📄 docs/index.rst",
        "📁 src/",
        "📄 src/main.py",
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

    def fake_get(url: str, headers: dict[str, str], timeout: int) -> Response:
        del url, headers, timeout
        calls["count"] += 1
        if calls["count"] < 3:
            return Response(502, {})
        return Response(200, {"ok": True})

    monkeypatch.setattr(github_client.requests, "get", fake_get)
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

    def fake_get(url: str, headers: dict[str, str], timeout: int) -> Response:
        del url, headers, timeout
        calls["count"] += 1
        if calls["count"] == 1:
            return Response(429, {}, retry_after="7")
        return Response(200, {"ok": True})

    monkeypatch.setattr(github_client.requests, "get", fake_get)
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

    monkeypatch.setattr(github_client.requests, "get", lambda *_args, **_kwargs: Response())

    with pytest.raises(RuntimeError) as exc_info:
        github_client.safe_get_json("https://api.github.com/repos/openai/openai-python")

    message = str(exc_info.value)
    assert "Set GITHUB_TOKEN" in message
    assert "1700000000" in message


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
