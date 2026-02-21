import json
from types import SimpleNamespace

import pytest
import requests

from repo_brief import agents_workflow as workflow
from repo_brief import github_client
from repo_brief.budget import validate_price_overrides
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

    def fake_run_sync(agent: object, prompt: str, max_turns: int) -> _DummyResult:
        del prompt, max_turns
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


def test_safe_get_json_retries_transient_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    class Response:
        def __init__(self, status_code: int, payload: dict[str, object]) -> None:
            self.status_code = status_code
            self._payload = payload

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
