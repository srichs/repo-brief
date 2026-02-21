import json
import sys
import types


def _install_test_stubs() -> None:
    requests_stub = types.ModuleType("requests")
    requests_stub.get = lambda *args, **kwargs: None
    requests_stub.HTTPError = Exception
    sys.modules.setdefault("requests", requests_stub)

    agents_stub = types.ModuleType("agents")

    class _DummyAgent:
        def __init__(self, *args, **kwargs) -> None:
            pass

    class _DummyRunner:
        @staticmethod
        def run_sync(*args, **kwargs):
            raise NotImplementedError

    agents_stub.Agent = _DummyAgent
    agents_stub.Runner = _DummyRunner
    agents_stub.function_tool = lambda f: f
    sys.modules.setdefault("agents", agents_stub)

    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda: None
    sys.modules.setdefault("dotenv", dotenv_stub)


_install_test_stubs()

from repo_brief.repo_brief import (  # noqa: E402
    _json_or_fallback,
    _parse_github_repo_url,
    _tree_summary,
    _truncate,
    _validate_price_overrides,
)


def test_parse_github_repo_url_accepts_valid_https_url() -> None:
    owner, repo = _parse_github_repo_url("https://github.com/openai/openai-python")
    assert owner == "openai"
    assert repo == "openai-python"


def test_parse_github_repo_url_rejects_invalid_url() -> None:
    try:
        _parse_github_repo_url("git@github.com:openai/openai-python.git")
        raise AssertionError("Expected ValueError")
    except ValueError:
        assert True


def test_json_fallback_uses_fallback_key_for_non_json() -> None:
    out = _json_or_fallback("plain text", fallback_key="reading_plan_markdown")
    assert out["reading_plan_markdown"] == "plain text"
    assert out["files_to_inspect"] == []


def test_truncate_shortens_long_strings() -> None:
    text = "x" * 60
    truncated = _truncate(text, max_chars=30)
    assert truncated.endswith("...[truncated]...")


def test_truncate_handles_non_positive_limit() -> None:
    assert _truncate("abcdef", max_chars=0) == ""


def test_validate_price_overrides_requires_both_values() -> None:
    try:
        _validate_price_overrides(price_in=1.0, price_out=None)
        raise AssertionError("Expected ValueError")
    except ValueError:
        assert True


def test_tree_summary_uses_folder_icon_for_directories() -> None:
    out = _tree_summary(["src/", "docs/"])
    assert "📁 src/" in out
    assert "📁 docs/" in out


def test_tree_summary_uses_file_icon_for_files() -> None:
    out = _tree_summary(["README.md", "src/main.py"])
    assert "📄 README.md" in out
    assert "📄 src/main.py" in out


def test_tree_summary_respects_max_entries() -> None:
    out = _tree_summary(["a.py", "b.py", "c.py"], max_entries=2)
    assert out.splitlines() == ["📄 a.py", "📄 b.py"]


def test_tree_summary_orders_paths_stably() -> None:
    out = _tree_summary(["b.py", "src/main.py", "a.py", "src/", "docs/"])
    assert out.splitlines() == ["📄 a.py", "📄 b.py", "📁 docs/", "📁 src/", "📄 src/main.py"]


def test_run_briefing_loop_fetches_repo_context_once(monkeypatch) -> None:
    import repo_brief.repo_brief as rb

    calls = {"count": 0}

    def fake_repo_context(repo_url: str, **kwargs):
        calls["count"] += 1
        return {
            "tree_summary": "📄 README.md",
            "key_files": ["README.md"],
        }

    class _DummyResult:
        def __init__(self, payload: dict[str, str]) -> None:
            self.final_output = json.dumps(payload)

    def fake_run_sync(agent, prompt: str, max_turns: int):
        if agent is rb.OverviewAgent:
            return _DummyResult({"briefing_markdown": "brief", "files_to_inspect": []})
        return _DummyResult({"reading_plan_markdown": "plan"})

    monkeypatch.setattr(rb, "_fetch_repo_context_impl", fake_repo_context)
    monkeypatch.setattr(rb.Runner, "run_sync", fake_run_sync)
    monkeypatch.setattr(rb, "usage_totals", lambda _result: {"total_tokens": 0, "requests": 1})
    monkeypatch.setattr(rb, "estimate_cost_usd", lambda _result, _pricing: 0.0)

    pricing = rb.Pricing(in_per_1m=0.0, out_per_1m=0.0, cached_in_per_1m=0.0)
    rb.run_briefing_loop(
        repo_url="https://github.com/openai/openai-python",
        model="gpt-4.1-mini",
        max_iters=2,
        max_turns=1,
        max_cost=0.0,
        max_tokens=0,
        pricing=pricing,
    )

    assert calls["count"] == 1
