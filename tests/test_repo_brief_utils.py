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
