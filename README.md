# repo-brief

`repo-brief` is an agentic CLI that analyzes a **public GitHub repository** and generates:

- an engineering briefing ("80% understanding")
- a practical reading plan to get productive quickly
- usage and estimated token-cost metadata

See an example output in [SUMMARY.md](./SUMMARY.md).

## How it works

`repo-brief` fetches GitHub repository metadata, the tree, and key files, then runs a multi-stage workflow:

1. Overview stage (repo understanding + candidate follow-up files)
2. Deep-dive loop (fetch selected files and refine understanding)
3. Reading-plan stage (ordered, practical reading sequence)

## Installation

```bash
pip install -e .
```

Then run:

```bash
repo-brief --help
```

## Requirements and environment variables

- Python 3.10+
- `OPENAI_API_KEY` (**required**)
- `GITHUB_TOKEN` (optional, recommended for higher GitHub API rate limits)

You can use a `.env` file:

```env
OPENAI_API_KEY=...
GITHUB_TOKEN=...
```

> GitHub API requests are rate-limited. Supplying `GITHUB_TOKEN` significantly increases limits.

## Usage

```bash
repo-brief https://github.com/OWNER/REPO
```

### JSON output to file

```bash
repo-brief https://github.com/OWNER/REPO \
  --format json \
  --output artifacts/repo-brief.json
```

## Development

Install development tooling and configure hooks:

```bash
pip install -e .[dev]
pre-commit install
pre-commit run --all-files
```

Quality checks:

```bash
pytest
ruff format --check .
ruff check .
mypy
sphinx-build -b html docs docs/_build/html
```

## Notes

- Only public repositories are supported by default.
- If the model emits non-JSON content, the CLI falls back gracefully.
- GitHub and model/API errors are surfaced with non-zero exit codes.
