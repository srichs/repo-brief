"""CLI entrypoint and output rendering for repo-brief."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import __version__


def render_output(result: dict[str, Any], output_format: str) -> str:
    """Render orchestrated results as JSON or markdown output."""
    if output_format == "json":
        return json.dumps(result, indent=2, ensure_ascii=False)

    parts = [result["briefing_markdown"].rstrip()]
    if result.get("reading_plan_markdown"):
        parts.append(result["reading_plan_markdown"].rstrip())
    elif result.get("stopped_reason") == "budget_exceeded":
        parts.append("_Reading plan skipped because the configured budget limit was reached._")

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


def write_output(output_text: str, output_path: str | None) -> None:
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
        description=(
            "Multi-agent GitHub repo briefing: URL -> 80% understanding "
            "(overview + deep-dive + reading plan)."
        ),
    )
    parser.add_argument("repo_url", nargs="?", help="e.g. https://github.com/OWNER/REPO")
    parser.add_argument("-V", "--version", action="store_true", help="Print package version.")
    parser.add_argument(
        "--model",
        default="gpt-4.1-mini",
        help="Model name (must match your org's enabled models).",
    )
    parser.add_argument(
        "--format", choices=["markdown", "json"], default="markdown", help="Output format."
    )
    parser.add_argument("--output", help="Write output to a file instead of stdout.")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print workflow diagnostics to stderr while keeping stdout output unchanged.",
    )
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
        "--max-tokens",
        type=int,
        default=0,
        help="Stop if total tokens >= this (0 disables).",
    )
    parser.add_argument(
        "--max-readme-chars",
        type=int,
        default=12000,
        help="Max README characters to include in repo context.",
    )
    parser.add_argument(
        "--max-tree-entries",
        type=int,
        default=350,
        help="Max repository tree entries to include in context.",
    )
    parser.add_argument(
        "--max-key-files",
        type=int,
        default=12,
        help="Max representative files to sample for context.",
    )
    parser.add_argument(
        "--max-file-chars",
        type=int,
        default=12000,
        help="Max characters captured per sampled file.",
    )
    parser.add_argument(
        "--ref",
        default="",
        help="Git ref to analyze (branch, tag, or commit SHA). Default: repo default branch.",
    )
    parser.add_argument("--price-in", type=float, default=None, help="Override input $/1M tokens.")
    parser.add_argument(
        "--price-out", type=float, default=None, help="Override output $/1M tokens."
    )
    parser.add_argument(
        "--price-cached-in",
        type=float,
        default=None,
        help="Override cached input $/1M tokens.",
    )
    return parser


def main() -> None:
    """CLI entrypoint with validation, orchestration, and error handling."""
    from .agents_workflow import run_briefing_loop
    from .budget import Pricing, validate_price_overrides
    from .github_client import parse_github_repo_url

    parser = build_parser()
    args = parser.parse_args()
    load_dotenv()

    if args.version:
        print(__version__)
        sys.exit(0)

    if not args.repo_url:
        parser.error("the following arguments are required: repo_url")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print(
            "ERROR: OPENAI_API_KEY is required. Set it in your environment or .env file.",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        owner, repo = parse_github_repo_url(args.repo_url)
    except ValueError as exc:
        print(
            f"ERROR: Invalid repository URL '{args.repo_url}'. Expected format: "
            "https://github.com/OWNER/REPO",
            file=sys.stderr,
        )
        print(f"DETAILS: {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        validate_price_overrides(args.price_in, args.price_out)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    pricing = Pricing.for_model(args.model, args.price_in, args.price_out, args.price_cached_in)

    if args.verbose:
        print(f"parsed repo: owner={owner}, repo={repo}", file=sys.stderr)

    diagnostics = (lambda message: print(message, file=sys.stderr)) if args.verbose else None

    try:
        result = run_briefing_loop(
            repo_url=args.repo_url,
            model=args.model,
            max_iters=max(0, args.max_iters),
            max_turns=max(1, args.max_turns),
            max_cost=max(0.0, args.max_cost),
            max_tokens=max(0, args.max_tokens),
            pricing=pricing,
            max_readme_chars=max(0, args.max_readme_chars),
            max_tree_entries=max(0, args.max_tree_entries),
            max_key_files=max(0, args.max_key_files),
            max_file_chars=max(0, args.max_file_chars),
            ref=args.ref,
            verbose=args.verbose,
            diagnostics=diagnostics,
        )
        write_output(render_output(result, args.format), args.output)
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
