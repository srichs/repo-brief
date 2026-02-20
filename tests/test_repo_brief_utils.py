from repo_brief.repo_brief import _json_or_fallback, _parse_github_repo_url, _truncate


def test_parse_github_repo_url_accepts_valid_https_url() -> None:
    owner, repo = _parse_github_repo_url("https://github.com/openai/openai-python")
    assert owner == "openai"
    assert repo == "openai-python"


def test_parse_github_repo_url_rejects_invalid_url() -> None:
    try:
        _parse_github_repo_url("git@github.com:openai/openai-python.git")
        assert False, "Expected ValueError"
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
