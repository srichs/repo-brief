"""CLI entrypoint and orchestration for generating GitHub repository briefings."""

import argparse
import base64
import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from agents import Agent, Runner, function_tool
from dotenv import load_dotenv

# ----------------------------
# Env / Config
# ----------------------------

load_dotenv()

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Minimal pricing map (USD per 1M tokens). Update as needed.
DEFAULT_PRICING_PER_1M = {
    "gpt-4.1-mini": {"in": 0.40, "out": 1.60, "cached_in": 0.10},
    "gpt-4.1": {"in": 2.00, "out": 8.00, "cached_in": 0.50},
    "_default": {"in": 1.00, "out": 4.00, "cached_in": 0.25},
}

ENV_PRICE_IN = os.getenv("PRICE_IN_PER_1M")
ENV_PRICE_OUT = os.getenv("PRICE_OUT_PER_1M")
ENV_PRICE_CACHED_IN = os.getenv("PRICE_CACHED_IN_PER_1M")


# ----------------------------
# GitHub helpers
# ----------------------------


def _parse_github_repo_url(repo_url: str) -> tuple[str, str]:
    """Parse a GitHub HTTPS repository URL into ``(owner, repo)``.

    Args:
        repo_url: URL in the form ``https://github.com/OWNER/REPO``.

    Returns:
        A tuple of repository owner and repository name.

    Raises:
        ValueError: If ``repo_url`` is not a supported GitHub HTTPS URL.
    """
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", repo_url.strip())
    if not m:
        raise ValueError("Expected https://github.com/OWNER/REPO")
    return m.group(1), m.group(2)


def _gh_headers() -> dict[str, str]:
    """Build GitHub API headers, including auth when available."""
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _safe_get_json(url: str, timeout: int = 25) -> Any:
    """Fetch JSON from a URL and raise for HTTP errors."""
    r = requests.get(url, headers=_gh_headers(), timeout=timeout)
    r.raise_for_status()
    return r.json()


def _truncate(s: str, max_chars: int) -> str:
    """Truncate a string to ``max_chars`` with a visible suffix."""
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "\n...[truncated]..."


def _build_tree_index(tree: list[dict[str, Any]]) -> dict[str, str]:
    """Convert a Git tree response into a ``path -> type`` mapping."""
    out: dict[str, str] = {}
    for item in tree:
        p = item.get("path")
        t = item.get("type")
        if p and t:
            out[p] = t
    return out


def _tree_summary(paths: list[str], max_entries: int = 300) -> str:
    """Render a sorted tree summary with file/folder icons."""
    paths = sorted(paths, key=lambda p: (p.count("/"), p))
    paths = paths[:max_entries]
    lines = []
    for p in paths:
        icon = "📁" if p.endswith("/") else "📄"
        lines.append(f"{icon} {p}")
    return "\n".join(lines)


def _pick_key_files(tree_index: dict[str, str], max_files: int) -> list[str]:
    """Pick representative files to bootstrap repository understanding."""
    candidates = [
        "README.md",
        "README.rst",
        "README.txt",
        "CONTRIBUTING.md",
        "LICENSE",
        "SECURITY.md",
        "CHANGELOG.md",
        "CODEOWNERS",
        ".env.example",
        ".env.sample",
        "Dockerfile",
        "docker-compose.yml",
        "compose.yml",
        "Makefile",
        "pyproject.toml",
        "requirements.txt",
        "Pipfile",
        "poetry.lock",
        "setup.py",
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "tsconfig.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
    ]

    found: list[str] = []
    present = set(tree_index.keys())

    for c in candidates:
        if c in present and tree_index[c] == "blob":
            found.append(c)

    for p in present:
        if tree_index.get(p) != "blob":
            continue
        lower = p.lower()
        if any(
            lower.endswith(x)
            for x in (
                "/main.py",
                "/app.py",
                "/server.py",
                "/cli.py",
                "/index.js",
                "/index.ts",
                "/main.go",
                "/main.rs",
                "/__init__.py",
            )
        ):
            found.append(p)
        if "/docs/" in lower and lower.endswith((".md", ".rst")):
            found.append(p)

    seen = set()
    uniq = []
    for f in found:
        if f not in seen:
            uniq.append(f)
            seen.add(f)

    return uniq[:max_files]


def _fetch_repo_tree(owner: str, repo: str, branch: str) -> list[dict[str, Any]]:
    """Fetch a repository tree recursively for a specific branch."""
    branch_obj = _safe_get_json(f"{GITHUB_API}/repos/{owner}/{repo}/branches/{branch}")
    sha = branch_obj["commit"]["sha"]
    tree_obj = _safe_get_json(f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{sha}?recursive=1")
    return tree_obj.get("tree", [])


def _fetch_file_content(owner: str, repo: str, path: str, ref: str, max_chars: int) -> str:
    """Fetch and decode file content from GitHub repository contents API."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}?ref={ref}"
    obj = _safe_get_json(url)
    if isinstance(obj, dict) and obj.get("type") == "file":
        content_b64 = obj.get("content", "")
        if content_b64:
            raw = base64.b64decode(content_b64).decode("utf-8", errors="replace")
            return _truncate(raw, max_chars)
    return ""


def get_final_text(run_result: Any) -> str:
    """Extract final text output from different Agents SDK result shapes."""
    for attr in ("final_output", "output", "output_text", "final_output_text", "text"):
        if hasattr(run_result, attr):
            val = getattr(run_result, attr)
            if isinstance(val, str) and val.strip():
                return val
    if hasattr(run_result, "messages"):
        msgs = run_result.messages or []
        for m in reversed(msgs):
            if isinstance(m, dict):
                content = m.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, list):
                    texts = []
                    for c in content:
                        if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                            texts.append(c.get("text", ""))
                    joined = "\n".join(t for t in texts if t)
                    if joined.strip():
                        return joined
            else:
                content = getattr(m, "content", None)
                if isinstance(content, str) and content.strip():
                    return content
    raise AttributeError(
        "Could not find final text on RunResult. Inspect dir(run_result) to see available fields."
    )


# ----------------------------
# Tool functions (Agents SDK)
# ----------------------------


def _fetch_repo_context_impl(
    repo_url: str,
    max_readme_chars: int = 12000,
    max_tree_entries: int = 350,
    max_key_files: int = 12,
    max_file_chars: int = 12000,
) -> dict[str, Any]:
    """Collect high-signal repository context for prompting downstream agents."""
    owner, repo = _parse_github_repo_url(repo_url)
    repo_meta = _safe_get_json(f"{GITHUB_API}/repos/{owner}/{repo}")
    default_branch = repo_meta.get("default_branch", "main")

    tree = _fetch_repo_tree(owner, repo, default_branch)
    tree_index = _build_tree_index(tree)

    paths_for_summary: list[str] = []
    for p, t in tree_index.items():
        lower = p.lower()
        if lower.startswith(("node_modules/", "dist/", "build/", ".git/", ".venv/", "venv/")):
            continue
        if t == "tree":
            paths_for_summary.append(p.rstrip("/") + "/")
        else:
            paths_for_summary.append(p)

    key_files = _pick_key_files(tree_index, max_files=max_key_files)

    files_content: dict[str, str] = {}
    for f in key_files:
        try:
            files_content[f] = _fetch_file_content(owner, repo, f, default_branch, max_file_chars)
        except Exception:
            files_content[f] = ""

    readme_text = files_content.get("README.md", "")
    if not readme_text:
        try:
            readme_obj = _safe_get_json(f"{GITHUB_API}/repos/{owner}/{repo}/readme")
            content_b64 = readme_obj.get("content", "")
            if content_b64:
                readme_text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
                readme_text = _truncate(readme_text, max_readme_chars)
        except Exception:
            readme_text = ""
    else:
        readme_text = _truncate(readme_text, max_readme_chars)

    return {
        "repo_url": repo_url,
        "owner": owner,
        "repo": repo,
        "full_name": repo_meta.get("full_name"),
        "description": repo_meta.get("description"),
        "stars": repo_meta.get("stargazers_count"),
        "language": repo_meta.get("language"),
        "topics": repo_meta.get("topics", []),
        "license": (repo_meta.get("license") or {}).get("spdx_id"),
        "default_branch": default_branch,
        "tree_summary": _tree_summary(paths_for_summary, max_entries=max_tree_entries),
        "key_files": key_files,
        "readme": readme_text,
        "key_file_contents": files_content,
    }


@function_tool
def fetch_repo_context(
    repo_url: str,
    max_readme_chars: int = 12000,
    max_tree_entries: int = 350,
    max_key_files: int = 12,
    max_file_chars: int = 12000,
) -> dict[str, Any]:
    """Agents tool wrapper for repository metadata and content sampling."""
    return _fetch_repo_context_impl(
        repo_url=repo_url,
        max_readme_chars=max_readme_chars,
        max_tree_entries=max_tree_entries,
        max_key_files=max_key_files,
        max_file_chars=max_file_chars,
    )


def _fetch_files_impl(
    repo_url: str,
    paths: list[str],
    max_file_chars: int = 16000,
) -> dict[str, Any]:
    """Fetch selected files from a repository default branch."""
    owner, repo = _parse_github_repo_url(repo_url)
    repo_meta = _safe_get_json(f"{GITHUB_API}/repos/{owner}/{repo}")
    default_branch = repo_meta.get("default_branch", "main")

    out: dict[str, str] = {}
    for p in paths:
        p = p.strip().lstrip("/")
        if not p:
            continue
        try:
            out[p] = _fetch_file_content(owner, repo, p, default_branch, max_file_chars)
        except Exception as e:
            out[p] = f"[Could not fetch {p}: {type(e).__name__}]"

    return {"repo_url": repo_url, "default_branch": default_branch, "files": out}


@function_tool
def fetch_files(repo_url: str, paths: list[str], max_file_chars: int = 16000) -> dict[str, Any]:
    """Agents tool wrapper for fetching specific repository files."""
    return _fetch_files_impl(repo_url=repo_url, paths=paths, max_file_chars=max_file_chars)


# ----------------------------
# Cost + Budget guard
# ----------------------------


@dataclass
class Pricing:
    """Model pricing information used to estimate prompt/completion costs."""

    in_per_1m: float
    out_per_1m: float
    cached_in_per_1m: float

    @staticmethod
    def for_model(
        model: str,
        price_in: float | None,
        price_out: float | None,
        price_cached_in: float | None,
    ) -> "Pricing":
        """Resolve pricing from CLI overrides, environment, or defaults."""
        if price_in is not None and price_out is not None:
            return Pricing(
                in_per_1m=price_in,
                out_per_1m=price_out,
                cached_in_per_1m=price_cached_in
                if price_cached_in is not None
                else DEFAULT_PRICING_PER_1M["_default"]["cached_in"],
            )

        if ENV_PRICE_IN and ENV_PRICE_OUT:
            return Pricing(
                in_per_1m=float(ENV_PRICE_IN),
                out_per_1m=float(ENV_PRICE_OUT),
                cached_in_per_1m=float(ENV_PRICE_CACHED_IN)
                if ENV_PRICE_CACHED_IN
                else DEFAULT_PRICING_PER_1M["_default"]["cached_in"],
            )

        entry = DEFAULT_PRICING_PER_1M.get(model, DEFAULT_PRICING_PER_1M["_default"])
        return Pricing(
            in_per_1m=entry["in"],
            out_per_1m=entry["out"],
            cached_in_per_1m=entry.get("cached_in", 0.0),
        )


def usage_totals(result: Any) -> dict[str, int]:
    """Aggregate token usage totals from an Agents SDK result object."""
    entries = result.context_wrapper.usage.request_usage_entries
    in_tokens = sum(getattr(e, "input_tokens", 0) for e in entries)
    out_tokens = sum(getattr(e, "output_tokens", 0) for e in entries)
    cached_in = sum(getattr(e, "cached_input_tokens", 0) for e in entries)
    return {
        "input_tokens": int(in_tokens),
        "output_tokens": int(out_tokens),
        "cached_input_tokens": int(cached_in),
        "total_tokens": int(in_tokens + out_tokens),
        "requests": len(entries),
    }


def estimate_cost_usd(result: Any, pricing: Pricing) -> float:
    """Estimate USD cost for a run result using configured pricing."""
    totals = usage_totals(result)
    in_cost = (totals["input_tokens"] / 1_000_000.0) * pricing.in_per_1m
    out_cost = (totals["output_tokens"] / 1_000_000.0) * pricing.out_per_1m
    cached_cost = (totals["cached_input_tokens"] / 1_000_000.0) * pricing.cached_in_per_1m
    return float(in_cost + out_cost + cached_cost)


# ----------------------------
# Agents (multi-agent loop)
# ----------------------------

OverviewAgent = Agent(
    name="Repo Overview Agent",
    instructions=textwrap.dedent(
        """
        You are a staff engineer. Goal: produce an "80% understanding" overview of a GitHub repo.

        Use the tool to fetch repo context: metadata, README, tree summary, and key file contents.

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
    tools=[fetch_repo_context],
)

DeepDiveAgent = Agent(
    name="Repo Deep Dive Agent",
    instructions=textwrap.dedent(
        """
        You are a staff engineer. You will be given:
        - the repo URL
        - the current briefing (markdown)
        - a list of file paths to fetch

        Use the tool to fetch those files, then improve the briefing with sharper, more 
        accurate details. Be explicit about what is supported by the files vs inferred.

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


def _json_or_fallback(text: str, fallback_key: str = "briefing_markdown") -> dict[str, Any]:
    """Parse model JSON output, or wrap raw text in a fallback dictionary."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    return {fallback_key: text, "files_to_inspect": []}


# ----------------------------
# Main orchestration loop
# ----------------------------


def run_briefing_loop(
    repo_url: str,
    model: str,
    max_iters: int,
    max_turns: int,
    max_cost: float,
    max_tokens: int,
    pricing: Pricing,
) -> dict[str, Any]:
    """Run overview, deep-dive, and reading-plan stages with budget guards."""
    accumulated_tokens = 0
    accumulated_cost = 0.0
    total_requests = 0

    overview_prompt = f"Analyze this repo and produce the JSON output: {repo_url}"
    overview_result = Runner.run_sync(OverviewAgent, overview_prompt, max_turns=max_turns)
    overview_usage = usage_totals(overview_result)
    overview_cost = estimate_cost_usd(overview_result, pricing)

    accumulated_tokens += overview_usage["total_tokens"]
    accumulated_cost += overview_cost
    total_requests += overview_usage["requests"]

    data = _json_or_fallback(get_final_text(overview_result))
    briefing = data.get("briefing_markdown", "")
    files_to_inspect = data.get("files_to_inspect", []) or []

    repo_context = _fetch_repo_context_impl(repo_url)

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
                "current_briefing_markdown": briefing,
                "inspect_these_paths": files_to_inspect,
                "instruction": "Fetch these files and improve the briefing JSON output.",
            },
            ensure_ascii=False,
        )

        deep_result = Runner.run_sync(DeepDiveAgent, deep_prompt, max_turns=max_turns)
        deep_usage = usage_totals(deep_result)
        deep_cost = estimate_cost_usd(deep_result, pricing)

        accumulated_tokens += deep_usage["total_tokens"]
        accumulated_cost += deep_cost
        total_requests += deep_usage["requests"]

        data2 = _json_or_fallback(get_final_text(deep_result))
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
        rp_result = Runner.run_sync(ReadingPlanAgent, rp_prompt, max_turns=max_turns)
        rp_usage = usage_totals(rp_result)
        rp_cost = estimate_cost_usd(rp_result, pricing)

        accumulated_tokens += rp_usage["total_tokens"]
        accumulated_cost += rp_cost
        total_requests += rp_usage["requests"]

        rp_data = _json_or_fallback(get_final_text(rp_result), fallback_key="reading_plan_markdown")
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
    }


def _render_output(result: dict[str, Any], output_format: str) -> str:
    """Render orchestrated results as JSON or markdown output."""
    if output_format == "json":
        return json.dumps(result, indent=2, ensure_ascii=False)

    parts = [result["briefing_markdown"].rstrip()]
    if result.get("reading_plan_markdown"):
        parts.append(result["reading_plan_markdown"].rstrip())

    parts.extend(
        [
            "---",
            f"- Estimated cost: ${result['usage']['estimated_cost_usd']}",
            f"- Tokens: {result['usage']['total_tokens']}",
            f"- Requests: {result['usage']['requests']}",
            f"- Stopped reason: {result['stopped_reason']}",
        ]
    )
    return "\n\n".join(parts)


def _write_output(output_text: str, output_path: str | None) -> None:
    """Write rendered output to stdout or a file path."""
    if not output_path:
        print(output_text)
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output_text + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """Build and return the command-line parser for ``repo-brief``."""
    parser = argparse.ArgumentParser(
        prog="repo-brief",
        description="""Multi-agent GitHub repo briefing: URL -> 80% understanding (overview + 
        deep-dive + reading plan).""",
    )
    parser.add_argument("repo_url", help="e.g. https://github.com/OWNER/REPO")
    parser.add_argument(
        "--model", default="gpt-4.1-mini", help="Model name (must match your org's enabled models)."
    )
    parser.add_argument(
        "--format", choices=["markdown", "json"], default="markdown", help="Output format."
    )
    parser.add_argument("--output", help="Write output to a file instead of stdout.")
    parser.add_argument(
        "--max-iters", type=int, default=2, help="Deep-dive iterations after overview."
    )
    parser.add_argument("--max-turns", type=int, default=12, help="Max turns per agent run.")
    parser.add_argument(
        "--max-cost",
        type=float,
        default=0.0,
        help="Stop if estimated cost >= this USD (0 disables).",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=0, help="Stop if total tokens >= this (0 disables)."
    )
    parser.add_argument("--price-in", type=float, default=None, help="Override input $/1M tokens.")
    parser.add_argument(
        "--price-out", type=float, default=None, help="Override output $/1M tokens."
    )
    parser.add_argument(
        "--price-cached-in", type=float, default=None, help="Override cached input $/1M tokens."
    )
    return parser


def main() -> None:
    """CLI entrypoint with validation, orchestration, and error handling."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        _parse_github_repo_url(args.repo_url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    if not os.getenv("OPENAI_API_KEY"):
        print(
            "ERROR: OPENAI_API_KEY not found. Put it in .env or your environment.", file=sys.stderr
        )
        sys.exit(2)

    pricing = Pricing.for_model(args.model, args.price_in, args.price_out, args.price_cached_in)

    try:
        result = run_briefing_loop(
            repo_url=args.repo_url,
            model=args.model,
            max_iters=max(0, args.max_iters),
            max_turns=max(1, args.max_turns),
            max_cost=max(0.0, args.max_cost),
            max_tokens=max(0, args.max_tokens),
            pricing=pricing,
        )
        _write_output(_render_output(result, args.format), args.output)
    except requests.HTTPError as exc:
        print(f"ERROR: GitHub API request failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
