"""GitHub API utilities for repository metadata and content retrieval."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import random
import re
import time
from typing import Any

import requests

from . import __version__

GITHUB_API = "https://api.github.com"
DEFAULT_TIMEOUT_SECONDS = 25
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 0.5
MAX_RETRY_AFTER_SECONDS = 10.0


def parse_github_repo_url(repo_url: str) -> tuple[str, str]:
    """Parse a GitHub HTTPS repository URL into ``(owner, repo)``."""
    match = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", repo_url.strip())
    if not match:
        raise ValueError("Expected https://github.com/OWNER/REPO")
    return match.group(1), match.group(2)


def gh_headers() -> dict[str, str]:
    """Build GitHub API headers, including auth when available."""
    github_token = os.getenv("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"repo-brief/{__version__}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    return headers


def _should_retry_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code <= 599


def _retry_after_seconds(retry_after: str | None) -> float | None:
    if retry_after is None:
        return None
    try:
        return max(0.0, min(float(retry_after), MAX_RETRY_AFTER_SECONDS))
    except ValueError:
        return None


def _rate_limit_error(url: str, response: requests.Response) -> RuntimeError:
    reset_unix = response.headers.get("X-RateLimit-Reset")
    reset_hint = ""
    if reset_unix:
        try:
            reset_dt = dt.datetime.fromtimestamp(int(reset_unix), tz=dt.timezone.utc)
            reset_hint = (
                f" Reset time: {reset_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (unix: {reset_unix})."
            )
        except ValueError:
            reset_hint = f" Reset time (unix): {reset_unix}."
    return RuntimeError(
        "GitHub API rate limit exceeded while requesting "
        f"{url}. Set GITHUB_TOKEN to raise your limits.{reset_hint}"
    )


def safe_get_json(
    url: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    session: requests.Session | None = None,
) -> Any:
    """Fetch JSON from a URL with small transient-error retries."""
    last_error: Exception | None = None
    session_obj = session or requests.Session()

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = session_obj.get(url, headers=gh_headers(), timeout=timeout)
            if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
                raise _rate_limit_error(url, response)
            if _should_retry_status(response.status_code) and attempt < MAX_RETRIES:
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                if response.status_code == 429 and retry_after is not None:
                    sleep_for = retry_after
                else:
                    sleep_for = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0.0, 0.05)
                time.sleep(sleep_for)
                continue
            response.raise_for_status()
            try:
                return response.json()
            except json.JSONDecodeError as error:
                snippet = response.text[:200].replace("\n", "\\n")
                raise RuntimeError(
                    "GitHub API returned non-JSON response "
                    f"(status {response.status_code}) for {url}. "
                    f"Check authentication/rate limits. Body snippet: {snippet}"
                ) from error
        except requests.HTTPError as error:
            status_code = error.response.status_code if error.response is not None else None
            if (
                status_code == 403
                and error.response is not None
                and error.response.headers.get("X-RateLimit-Remaining") == "0"
            ):
                raise _rate_limit_error(url, error.response) from error
            if (
                status_code is not None
                and _should_retry_status(status_code)
                and attempt < MAX_RETRIES
            ):
                retry_after = None
                if error.response is not None and status_code == 429:
                    retry_after = _retry_after_seconds(error.response.headers.get("Retry-After"))
                if retry_after is not None:
                    sleep_for = retry_after
                else:
                    sleep_for = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0.0, 0.05)
                time.sleep(sleep_for)
                last_error = error
                continue
            raise RuntimeError(f"GitHub API request failed for {url}: {error}") from error
        except requests.RequestException as error:
            if attempt < MAX_RETRIES:
                sleep_for = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0.0, 0.05)
                time.sleep(sleep_for)
                last_error = error
                continue
            raise RuntimeError(f"GitHub API request failed for {url}: {error}") from error

    raise RuntimeError(f"GitHub API request failed for {url}: {last_error}")


def truncate(text: str, max_chars: int) -> str:
    """Truncate a string to ``max_chars`` with a visible suffix."""
    if max_chars <= 0:
        return ""

    suffix = "\n...[truncated]..."
    if len(text) <= max_chars:
        return text
    if max_chars <= len(suffix):
        return suffix[:max_chars]
    return text[: max_chars - len(suffix)] + suffix


def build_tree_index(tree: list[dict[str, Any]]) -> dict[str, str]:
    """Convert a Git tree response into a ``path -> type`` mapping."""
    out: dict[str, str] = {}
    for item in tree:
        path = item.get("path")
        item_type = item.get("type")
        if path and item_type:
            out[path] = item_type
    return out


def tree_summary(paths: list[str], max_entries: int = 300) -> str:
    """Render a sorted tree summary with 📁 for directories and 📄 for files."""
    ordered_paths = sorted(paths, key=lambda path: (path.count("/"), path))[:max_entries]
    return "\n".join(f"{'📁' if path.endswith('/') else '📄'} {path}" for path in ordered_paths)


def pick_key_files(tree_index: dict[str, str], max_files: int) -> list[str]:
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
    present = set(tree_index)

    for candidate in candidates:
        if candidate in present and tree_index[candidate] == "blob":
            found.append(candidate)

    for path in present:
        if tree_index.get(path) != "blob":
            continue
        lower = path.lower()
        if any(
            lower.endswith(suffix)
            for suffix in (
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
            found.append(path)
        if "/docs/" in lower and lower.endswith((".md", ".rst")):
            found.append(path)

    unique: list[str] = []
    seen: set[str] = set()
    for file_path in found:
        if file_path not in seen:
            seen.add(file_path)
            unique.append(file_path)
    return unique[:max_files]


def fetch_repo_tree(owner: str, repo: str, branch: str) -> list[dict[str, Any]]:
    """Fetch a repository tree recursively for a specific branch or ref."""
    tree_sha = ""
    try:
        branch_obj = safe_get_json(f"{GITHUB_API}/repos/{owner}/{repo}/branches/{branch}")
        tree_sha = str(
            (((branch_obj.get("commit") or {}).get("commit") or {}).get("tree") or {}).get("sha")
            or ""
        )
    except RuntimeError:
        commit_obj = safe_get_json(f"{GITHUB_API}/repos/{owner}/{repo}/commits/{branch}")
        tree_sha = ((commit_obj.get("commit") or {}).get("tree") or {}).get("sha", "")

    if not tree_sha:
        raise RuntimeError(f"Could not resolve repository tree SHA for {owner}/{repo}@{branch}")

    tree_obj = safe_get_json(f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1")
    tree = tree_obj.get("tree", []) if isinstance(tree_obj, dict) else []
    return tree if isinstance(tree, list) else []


def fetch_file_content(owner: str, repo: str, path: str, ref: str, max_chars: int) -> str:
    """Fetch and decode file content from GitHub repository contents API."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}?ref={ref}"
    obj = safe_get_json(url)
    if isinstance(obj, dict) and obj.get("type") == "file":
        content_b64 = obj.get("content", "")
        if content_b64:
            raw = base64.b64decode(content_b64).decode("utf-8", errors="replace")
            return truncate(raw, max_chars)
    return ""


def fetch_repo_context_impl(
    repo_url: str,
    max_readme_chars: int = 12000,
    max_tree_entries: int = 350,
    max_key_files: int = 12,
    max_file_chars: int = 12000,
    ref: str = "",
) -> dict[str, Any]:
    """Collect high-signal repository context for prompting downstream agents."""
    owner, repo = parse_github_repo_url(repo_url)
    repo_meta: dict[str, Any] = {}
    resolved_ref = ref
    if not resolved_ref:
        repo_meta = safe_get_json(f"{GITHUB_API}/repos/{owner}/{repo}")
        resolved_ref = repo_meta.get("default_branch", "main")

    tree = fetch_repo_tree(owner, repo, resolved_ref)
    tree_index = build_tree_index(tree)

    paths_for_summary: list[str] = []
    for path, item_type in tree_index.items():
        lower = path.lower()
        if lower.startswith(("node_modules/", "dist/", "build/", ".git/", ".venv/", "venv/")):
            continue
        if item_type == "tree":
            paths_for_summary.append(path.rstrip("/") + "/")
        else:
            paths_for_summary.append(path)

    key_files = pick_key_files(tree_index, max_files=max_key_files)

    files_content: dict[str, str] = {}
    for file_path in key_files:
        try:
            files_content[file_path] = fetch_file_content(
                owner,
                repo,
                file_path,
                resolved_ref,
                max_file_chars,
            )
        except Exception:
            files_content[file_path] = ""

    readme_text = files_content.get("README.md", "")
    if not readme_text:
        try:
            readme_obj = safe_get_json(
                f"{GITHUB_API}/repos/{owner}/{repo}/readme?ref={resolved_ref}"
            )
            content_b64 = readme_obj.get("content", "")
            if content_b64:
                readme_text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
                readme_text = truncate(readme_text, max_readme_chars)
        except Exception:
            readme_text = ""
    else:
        readme_text = truncate(readme_text, max_readme_chars)

    return {
        "repo_url": repo_url,
        "owner": owner,
        "repo": repo,
        "full_name": repo_meta.get("full_name") or f"{owner}/{repo}",
        "description": repo_meta.get("description"),
        "stars": repo_meta.get("stargazers_count"),
        "language": repo_meta.get("language"),
        "topics": repo_meta.get("topics", []),
        "license": (repo_meta.get("license") or {}).get("spdx_id"),
        "default_branch": repo_meta.get("default_branch"),
        "ref": resolved_ref,
        "tree_summary": tree_summary(paths_for_summary, max_entries=max_tree_entries),
        "key_files": key_files,
        "readme": readme_text,
        "key_file_contents": files_content,
    }


def fetch_files_impl(
    repo_url: str,
    paths: list[str],
    max_file_chars: int = 16000,
    default_branch: str | None = None,
    ref: str = "",
) -> dict[str, Any]:
    """Fetch selected files from a repository branch, tag, or commit ref."""
    owner, repo = parse_github_repo_url(repo_url)
    selected_ref = ref or default_branch
    if not selected_ref:
        repo_meta = safe_get_json(f"{GITHUB_API}/repos/{owner}/{repo}")
        selected_ref = repo_meta.get("default_branch", "main")

    out: dict[str, str] = {}
    for path in paths:
        cleaned_path = path.strip().lstrip("/")
        if not cleaned_path:
            continue
        try:
            out[cleaned_path] = fetch_file_content(
                owner, repo, cleaned_path, selected_ref, max_file_chars
            )
        except Exception as error:  # pragma: no cover - defensive behavior unchanged
            out[cleaned_path] = f"[Could not fetch {cleaned_path}: {type(error).__name__}]"

    return {
        "repo_url": repo_url,
        "default_branch": selected_ref,
        "ref": selected_ref,
        "files": out,
    }
