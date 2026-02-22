import json

from repo_brief.cli import build_parser, render_output, write_output
from repo_brief.github_client import parse_github_repo_url


def test_render_output_json_is_valid_json() -> None:
    payload = {
        "briefing_markdown": "# Brief",
        "reading_plan_markdown": "## Plan",
        "stopped_reason": "completed",
        "usage": {"estimated_cost_usd": 0.1, "total_tokens": 123, "requests": 2},
    }

    rendered = render_output(payload, "json")

    assert json.loads(rendered) == payload


def test_render_output_markdown_includes_briefing_plan_and_usage() -> None:
    payload = {
        "briefing_markdown": "# Brief\n",
        "reading_plan_markdown": "## Plan\n",
        "stopped_reason": "completed",
        "usage": {"estimated_cost_usd": 0.1, "total_tokens": 123, "requests": 2},
    }

    rendered = render_output(payload, "markdown")

    assert "# Brief" in rendered
    assert "## Plan" in rendered
    assert "- Tokens: 123" in rendered


def test_render_output_markdown_includes_budget_skip_note() -> None:
    payload = {
        "briefing_markdown": "# Brief",
        "reading_plan_markdown": "",
        "stopped_reason": "budget_exceeded",
        "usage": {"estimated_cost_usd": 0.1, "total_tokens": 123, "requests": 2},
    }

    rendered = render_output(payload, "markdown")

    assert "Reading plan skipped because the configured budget limit was reached" in rendered


def test_write_output_writes_to_stdout_for_none_and_dash(capsys) -> None:
    write_output("hello", None)
    write_output("world", "-")

    captured = capsys.readouterr()
    assert captured.out == "hello\nworld\n"


def test_write_output_writes_to_file(tmp_path) -> None:
    output_file = tmp_path / "out" / "brief.md"

    write_output("hello", str(output_file))

    assert output_file.read_text(encoding="utf-8") == "hello\n"


def test_build_parser_contains_key_arguments() -> None:
    parser = build_parser()
    argument_names = {
        option
        for action in parser._actions
        for option in [*action.option_strings, action.dest]
        if option
    }

    assert "repo_url" in argument_names
    assert "--model" in argument_names
    assert "--format" in argument_names
    assert "--output" in argument_names
    assert "--no-dotenv" in argument_names


def test_parse_github_repo_url_accepts_git_suffix_and_trailing_slash() -> None:
    owner, repo = parse_github_repo_url("https://github.com/openai/openai-python.git/")
    assert owner == "openai"
    assert repo == "openai-python"
