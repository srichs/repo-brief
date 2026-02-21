"""Agents definitions and orchestration flow for repo-brief."""

from __future__ import annotations

import json
import textwrap
from collections.abc import Callable
from typing import Any

from agents import Agent, RunConfig, Runner, function_tool

from .budget import Pricing, estimate_cost_usd, usage_totals
from .github_client import fetch_files_impl, fetch_repo_context_impl


@function_tool
def fetch_repo_context(
    repo_url: str,
    max_readme_chars: int = 12000,
    max_tree_entries: int = 350,
    max_key_files: int = 12,
    max_file_chars: int = 12000,
    ref: str = "",
) -> dict[str, Any]:
    """Agents tool wrapper for repository metadata and content sampling."""
    return fetch_repo_context_impl(
        repo_url=repo_url,
        max_readme_chars=max_readme_chars,
        max_tree_entries=max_tree_entries,
        max_key_files=max_key_files,
        max_file_chars=max_file_chars,
        ref=ref,
    )


@function_tool
def fetch_files(
    repo_url: str,
    paths: list[str],
    max_file_chars: int = 16000,
    default_branch: str | None = None,
    ref: str = "",
) -> dict[str, Any]:
    """Agents tool wrapper for fetching specific repository files."""
    return fetch_files_impl(
        repo_url=repo_url,
        paths=paths,
        max_file_chars=max_file_chars,
        default_branch=default_branch,
        ref=ref,
    )


OverviewAgent = Agent(
    name="Repo Overview Agent",
    instructions=textwrap.dedent(
        """
        You are a staff engineer. Goal: produce an "80% understanding" overview of a GitHub repo.

        You will be given repo_context JSON that includes metadata, README, tree summary,
        key files, and key file contents.

        OUTPUT MUST BE VALID JSON with this schema:
        {
          "briefing_markdown": "string (markdown)",
          "files_to_inspect": ["path1", "path2", ...]  // 0-8 paths for follow-up deep dive
        }

        Briefing requirements (in the markdown string):
        - What it is / who it's for
        - Key features
        - Architecture overview (major dirs/modules)
        - Execution model / entrypoints (CLI/web/service)
        - How to run locally (only if evidenced; otherwise say unknown)
        - Config/env vars (only if evidenced; don't invent)
        - Data flow (APIs/DB/queues) if evidenced
        - Extension points / where to start reading
        - Risks/gotchas (tests, build complexity, etc.) if evidenced
        - End with "Suggested first 3 files to read" and "Open questions"

        Choose files_to_inspect based on likely entrypoints and core logic.
        If unsure, pick entrypoints + config files.
        """
    ).strip(),
    tools=[],
)

DeepDiveAgent = Agent(
    name="Repo Deep Dive Agent",
    instructions=textwrap.dedent(
        """
        You are a staff engineer. You will be given:
        - the repo URL
        - the repository ref to use for file fetches (branch/tag/commit SHA)
        - the current briefing (markdown)
        - a list of file paths to fetch

        Use the tool to fetch those files, then improve the briefing with sharper, more
        accurate details. Be explicit about what is supported by the files vs inferred.
        When calling the tool, pass through the ref provided in the input.

        OUTPUT MUST BE VALID JSON with this schema:
        {
          "briefing_markdown": "string (markdown, updated)",
          "files_to_inspect": ["path1", ...]  // 0-6 additional paths if needed
        }

        Keep it succinct and focused on 80% understanding.
        """
    ).strip(),
    tools=[fetch_files],
)

ReadingPlanAgent = Agent(
    name="Repo Reading Plan Agent",
    instructions=textwrap.dedent(
        """
        You are a staff engineer writing a practical reading plan to get productive fast.

        You will be given:
        - repo URL
        - the final briefing markdown
        - optional repo context (tree summary + key files)

        OUTPUT MUST BE VALID JSON with this schema:
        {
          "reading_plan_markdown": "string (markdown)"
        }

        Requirements for reading_plan_markdown:
        - Title: "Reading plan"
        - Give an ordered list of 8–15 items max.
        - Each item must include:
          * file/path (or directory) to read
          * why it matters (1 sentence)
          * what to look for (1–3 bullets)
          * time estimate (e.g., 5–15 min)
        - Include a short "If you only have 30 minutes" subsection (3 steps).
        - Include a short "If you need to make a change safely" subsection:
          * how to run tests/build (if known), or what to verify if unknown
          * where to add a small change and validate quickly
        - Don’t invent file paths. Only use paths that appear in the provided context,
          or use clearly labeled directory-level guidance (e.g., "src/").
        """
    ).strip(),
    tools=[],
)


def get_final_text(run_result: Any) -> str:
    """Extract final text output from different Agents SDK result shapes."""
    for attr in ("final_output", "output", "output_text", "final_output_text", "text"):
        if hasattr(run_result, attr):
            val = getattr(run_result, attr)
            if isinstance(val, str) and val.strip():
                return val
    if hasattr(run_result, "messages"):
        msgs = run_result.messages or []
        for message in reversed(msgs):
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, list):
                    texts = []
                    for chunk in content:
                        if isinstance(chunk, dict) and chunk.get("type") in ("output_text", "text"):
                            texts.append(chunk.get("text", ""))
                    joined = "\n".join(text for text in texts if text)
                    if joined.strip():
                        return joined
            else:
                content = getattr(message, "content", None)
                if isinstance(content, str) and content.strip():
                    return content
    raise AttributeError(
        "Could not find final text on RunResult. Inspect dir(run_result) to see available fields."
    )


def json_or_fallback(text: str, fallback_key: str = "briefing_markdown") -> dict[str, Any]:
    """Parse model JSON output, or wrap raw text in a fallback dictionary."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    return {fallback_key: text, "files_to_inspect": []}


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def validate_overview_output(payload: dict[str, Any]) -> bool:
    """Validate overview-agent JSON schema."""
    return isinstance(payload.get("briefing_markdown"), str) and _is_string_list(
        payload.get("files_to_inspect")
    )


def validate_deep_dive_output(payload: dict[str, Any]) -> bool:
    """Validate deep-dive JSON schema."""
    if not isinstance(payload.get("briefing_markdown"), str):
        return False
    if "files_to_inspect" not in payload:
        return True
    return _is_string_list(payload.get("files_to_inspect"))


def validate_reading_plan_output(payload: dict[str, Any]) -> bool:
    """Validate reading-plan JSON schema."""
    return isinstance(payload.get("reading_plan_markdown"), str)


def run_briefing_loop(
    repo_url: str,
    model: str,
    max_iters: int,
    max_turns: int,
    max_cost: float,
    max_tokens: int,
    pricing: Pricing,
    max_readme_chars: int = 12000,
    max_tree_entries: int = 350,
    max_key_files: int = 12,
    max_file_chars: int = 12000,
    ref: str = "",
    verbose: bool = False,
    diagnostics: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run overview, deep-dive, and reading-plan stages with budget guards."""

    def log(message: str) -> None:
        if verbose and diagnostics is not None:
            diagnostics(message)

    repo_context = fetch_repo_context_impl(
        repo_url,
        max_readme_chars=max_readme_chars,
        max_tree_entries=max_tree_entries,
        max_key_files=max_key_files,
        max_file_chars=max_file_chars,
        ref=ref,
    )
    log(
        "repo context: "
        f"default_branch={repo_context.get('default_branch') or repo_context.get('ref', 'main')} "
        f"tree_entries={len(repo_context.get('tree_summary', '').splitlines())} "
        f"key_files={repo_context.get('key_files', [])}"
    )

    accumulated_tokens = 0
    accumulated_cost = 0.0
    total_requests = 0
    warnings: list[str] = []

    overview_prompt = json.dumps(
        {
            "repo_url": repo_url,
            "ref": repo_context.get("ref", ref),
            "repo_context": repo_context,
            "instruction": "Analyze this repo context and produce the required JSON output.",
        },
        ensure_ascii=False,
    )
    log("stage: overview")
    overview_result = Runner.run_sync(
        OverviewAgent,
        overview_prompt,
        max_turns=max_turns,
        run_config=RunConfig(model=model),
    )
    overview_usage = usage_totals(overview_result)
    overview_cost = estimate_cost_usd(overview_result, pricing)

    accumulated_tokens += overview_usage["total_tokens"]
    accumulated_cost += overview_cost
    total_requests += overview_usage["requests"]

    overview_text = get_final_text(overview_result)
    data = json_or_fallback(overview_text)
    if not validate_overview_output(data):
        warnings.append("overview stage returned invalid JSON schema; used text fallback")
        data = {"briefing_markdown": overview_text, "files_to_inspect": []}
    briefing = data.get("briefing_markdown", "")
    files_to_inspect = data.get("files_to_inspect", []) or []

    def budget_exceeded() -> bool:
        if max_tokens > 0 and accumulated_tokens >= max_tokens:
            return True
        return bool(max_cost > 0 and accumulated_cost >= max_cost)

    it = 0
    while it < max_iters and files_to_inspect and not budget_exceeded():
        it += 1

        deep_prompt = json.dumps(
            {
                "repo_url": repo_url,
                "default_branch": repo_context.get("default_branch")
                or repo_context.get("ref", ref)
                or "main",
                "ref": repo_context.get("ref", ref),
                "current_briefing_markdown": briefing,
                "inspect_these_paths": files_to_inspect,
                "instruction": "Fetch these files and improve the briefing JSON output.",
            },
            ensure_ascii=False,
        )

        log(f"stage: deep dive {it}")
        deep_result = Runner.run_sync(
            DeepDiveAgent,
            deep_prompt,
            max_turns=max_turns,
            run_config=RunConfig(model=model),
        )
        deep_usage = usage_totals(deep_result)
        deep_cost = estimate_cost_usd(deep_result, pricing)

        accumulated_tokens += deep_usage["total_tokens"]
        accumulated_cost += deep_cost
        total_requests += deep_usage["requests"]

        deep_text = get_final_text(deep_result)
        data2 = json_or_fallback(deep_text)
        if not validate_deep_dive_output(data2):
            warnings.append(
                f"deep dive {it} stage returned invalid JSON schema; used text fallback"
            )
            data2 = {"briefing_markdown": deep_text, "files_to_inspect": []}
        briefing = data2.get("briefing_markdown", briefing)
        files_to_inspect = data2.get("files_to_inspect", []) or []

    reading_plan_markdown = ""
    if not budget_exceeded():
        rp_prompt = json.dumps(
            {
                "repo_url": repo_url,
                "final_briefing_markdown": briefing,
                "tree_summary": repo_context.get("tree_summary", ""),
                "known_paths": repo_context.get("key_files", []),
                "note": "Only use file paths that appear in known_paths or tree_summary.",
            },
            ensure_ascii=False,
        )
        log("stage: reading plan")
        rp_result = Runner.run_sync(
            ReadingPlanAgent,
            rp_prompt,
            max_turns=max_turns,
            run_config=RunConfig(model=model),
        )
        rp_usage = usage_totals(rp_result)
        rp_cost = estimate_cost_usd(rp_result, pricing)

        accumulated_tokens += rp_usage["total_tokens"]
        accumulated_cost += rp_cost
        total_requests += rp_usage["requests"]

        reading_plan_text = get_final_text(rp_result)
        rp_data = json_or_fallback(reading_plan_text, fallback_key="reading_plan_markdown")
        if not validate_reading_plan_output(rp_data):
            warnings.append("reading plan stage returned invalid JSON schema; used text fallback")
            rp_data = {"reading_plan_markdown": reading_plan_text, "files_to_inspect": []}
        reading_plan_markdown = rp_data.get("reading_plan_markdown", "")

    stopped_reason = (
        "budget_exceeded"
        if (max_tokens > 0 and accumulated_tokens >= max_tokens)
        or (max_cost > 0 and accumulated_cost >= max_cost)
        else "completed"
    )

    return {
        "repo_url": repo_url,
        "model": model,
        "briefing_markdown": briefing,
        "reading_plan_markdown": reading_plan_markdown,
        "budget": {
            "max_cost_usd": max_cost,
            "max_tokens": max_tokens,
        },
        "usage": {
            "total_tokens": accumulated_tokens,
            "estimated_cost_usd": round(accumulated_cost, 6),
            "requests": total_requests,
        },
        "stopped_reason": stopped_reason,
        "warnings": warnings,
    }
