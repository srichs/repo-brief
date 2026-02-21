# repo-brief: 80% Understanding Overview

## What it is / Who it's for
`repo-brief` is an agentic command-line utility for software engineers, tech leads, and researchers who need high-signal onboarding into public GitHub repositories. It streamlines engineering briefings and reading plans for rapid project immersion.

## Key Features (Supported by Files)
- **Multi-agent workflow:** Orchestrates summarization and reading plan agents using a multi-step process (README.md confirms overview → deep dive loop → reading plan).
- **CLI and library usage:** Installable as an editable package; run as `repo-brief` command or via `python -m repo_brief`. (pyproject.toml and README.md)
- **Flexible outputs:** Produces summaries in JSON or Markdown, outputs to console or optional disk path (`--output`).
- **Budget/token controls:** Supports `--max-cost`, `--max-tokens`, and related env variables for cost-aware operation.
- **Public GitHub repo introspection:** Gathers GitHub metadata, file tree, and samples "key files" (README.md).
- **Dev & CI Ready:** Uses `pytest`, `ruff`, `mypy`, and supports `.env` (
README.md).
- **Graceful fallback for non-JSON responses:** If the OpenAI agent emits non-JSON, CLI falls back to a markdown/text output (test evidenced).

## Architecture Overview (Directly Evidenced)
- **Main logic:** Agent orchestration and command-line logic centers in `src/repo_brief/repo_brief.py`. Multi-agent pattern confirmed in README and referenced agent helpers in tests.
- **Entrypoint:** `main()` in `src/repo_brief/repo_brief.py` is invoked from `src/repo_brief/__main__.py` for CLI execution; exposure as setuptools console script.
- **Agent state & tools:** Not directly evidenced (could not fetch agents.py), but README confirms agents are central.
- **Config:** Driven by `pyproject.toml`; all Python/dev/test tools (ruff, mypy, pytest) declared there.     

## Execution Model / Entrypoints
- **CLI Entrypoints:**
  - As `repo-brief ...` (via setuptools script in pyproject.toml)
  - Or as `python -m repo_brief` (`src/repo_brief/__main__.py` imports and runs main())
- **Entrypoint Function:** `main()` in `src/repo_brief/repo_brief.py`

## How to Run Locally (All Evidenced)
- Install: `pip install -e .` (editable/dev install)
- Run CLI: `repo-brief --help` or `repo-brief <github-repo-url>`
- Requires Python 3.10+
- Set env vars: `OPENAI_API_KEY` (required), `GITHUB_TOKEN` (optional for API rate limits), via shell or `.env` file
- Run tests: `pytest`, lint/format with ruff, mypy

## Config / Env Vars (Evidenced)
- `OPENAI_API_KEY` (**required**)
- `GITHUB_TOKEN` (optional)
- Reads from `.env` if available
- Cost-control env vars (`PRICE_IN_PER_1M`, etc.) supported but specific handling logic only partially confirmed

## Data Flow (Supported by Files)
- Fetches repo metadata, file tree, and selected file contents via GitHub API.
- Agents process this context for summaries and reading plans. Output goes to stdout or to file (`--output`); fallback output is text/markdown as needed.
- Errors (API/model/parse) surfaced with non-zero exit codes (README.md confirms)

## Extension Points / Where to Start Reading
- **Start with:** `src/repo_brief/repo_brief.py` (core CLI/agent logic, helpers, config)
- **Entrypoint:** `src/repo_brief/__main__.py`
- **Project setup/dev logic:** `pyproject.toml` (deps, build, dev/test tools)
- **Test helpers/edge cases:** `tests/test_repo_brief_utils.py` (parsing, output handling)

## Risks / Gotchas (Directly Evidenced)
- **Only public GitHub repos** supported (README.md)
- **API/model costs:** User-controlled limits; estimation helpers used in CLI logic
- **Minimal formal tests:** `tests/test_repo_brief_utils.py` covers basic parsing, fallback, and truncation utilities
- **OpenAI/Agents dependency:** Reliant on third-party libs for agent orchestration and model calls
- **Non-JSON model output:** Handled gracefully; CLI falls back to markdown/text (test evidenced)
- **Errors bubble as exit codes** (README)

---
### Suggested first 3 files to read
1. `src/repo_brief/repo_brief.py` (core orchestration, CLI/agent logic)
2. `src/repo_brief/__main__.py` (simple entrypoint)
3. `pyproject.toml` (setup, dependencies, dev tools, metadata)

### Open Questions (Not fully answered by available evidence)
- Details on agent state handling, memory, or explicit tool interfaces (unable to fetch agents.py for specifics)
- Degree and strategy for autodetecting "key files"
- Documentation or guides for extending with new agent types/tools

# Reading plan

Get rapidly productive with the `repo-brief` codebase by following this stepwise reading plan. Prioritize files central to orchestration, entrypoints, config, and tests. Estimated total time: 70–120 min.

---

1. **README.md**
   _Why:_ Establishes goals, core features, usage, and troubleshooting at a glance.
   **What to look for:**
   - CLI usage examples and requirements
   - Key features and constraints (e.g., supported env vars, API keys, error handling)
   - How to run locally vs. in CI
   **Time estimate:** 10–15 min

2. **src/repo_brief/repo_brief.py**
   _Why:_ This is the heart of command-line orchestration and agent logic.
   **What to look for:**
   - The `main()` function: argument parsing, workflow
   - Agent orchestration flow (how summaries/reading plans are generated)
   - Cost/token budget handling
   **Time estimate:** 15–25 min

3. **src/repo_brief/__main__.py**
   _Why:_ Defines the package CLI entrypoint; see how the main orchestration is triggered.
   **What to look for:**
   - How execution transfers from CLI to `repo_brief.py`
   - Any argument transformation or setup
   **Time estimate:** 3–5 min

4. **pyproject.toml**
   _Why:_ Specifies all dependencies, packaging, and dev/test tools required for development and CI.
   **What to look for:**
   - `dependencies` and `dev-dependencies`
   - `[tool.poetry.scripts]` or similar (exposes CLI as `repo-brief`)
   - Linting, formatting, test, and Python version constraints
   **Time estimate:** 10–15 min

5. **tests/test_repo_brief_utils.py**
   _Why:_ Shows which core utility behaviors and fallback scenarios are covered by tests.
   **What to look for:**
   - Edge cases handled (non-JSON output, parsing, truncation)
   - Testing patterns and assertions
   - How test context is set up
   **Time estimate:** 10–15 min

6. **src/repo_brief/__init__.py**
   _Why:_ Documents package initialization, public symbols, and module-level metadata.
   **What to look for:**
   - Exposed imports (if any)
   - Docstrings or versioning details
   **Time estimate:** 2–3 min

7. **.github/workflows/ci.yml**
   _Why:_ Outlines automated build and test processes, ensuring you know CI expectations.
   **What to look for:**
   - Python versions/environments used in CI
   - Which checks (tests, lint, mypy) are run
   - Triggers and caching strategies
   **Time estimate:** 7–10 min

8. **docs/index.rst**
   _Why:_ Starting point for project Sphinx documentation, setting documentation intent and structure.       
   **What to look for:**
   - Main headings and structure
   - What sections are emphasized (API, usage, etc.)
   **Time estimate:** 5 min

9. **docs/usage.rst**
   _Why:_ Offers worked CLI usage examples, complements README with more detail.
   **What to look for:**
   - CLI invocation examples, options, and expected outputs
   - Troubleshooting or notes on environment variables
   **Time estimate:** 5–8 min

10. **docs/api.rst**
    _Why:_ (If present) Summarizes the main public classes/functions offered by the package.
    **What to look for:**
    - Listed functions/modules/classes
    - Prominent usage examples
    **Time estimate:** 5 min

---

## If you only have 30 minutes
1. **README.md** (understand what, why, and how to run) — 10–15 min
2. **src/repo_brief/repo_brief.py** (core CLI/logic structure) — 15 min
3. **pyproject.toml** (see dependencies, entrypoints, tooling) — 5 min

---

## If you need to make a change safely
- **How to run tests/build:**
  - Run `pytest` from the repo root (tests live in `tests/`—see `tests/test_repo_brief_utils.py`).
  - Lint with `ruff`, typecheck with `mypy` (configured in `pyproject.toml`).
- **Where to add a small change and validate quickly:**
  - Make the change in `src/repo_brief/repo_brief.py` (e.g., tweak CLI parsing or error handling), then add/modify a utility or test in `tests/test_repo_brief_utils.py`.
  - Run `pytest` to validate, and check for linter/type errors.
- **What to verify:**
  - Ensure the CLI still works (`repo-brief --help`), test output is as expected for both JSON and non-JSON cases, and automated CI checks pass (refer to `.github/workflows/ci.yml`).

---