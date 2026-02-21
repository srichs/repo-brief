# repo-brief

`repo-brief` is an agentic CLI that analyzes a **public GitHub repository** and generates:

- an engineering briefing ("80% understanding")
- a practical reading plan to get productive quickly
- usage and estimated token-cost metadata

See an example output [here](./SUMMARY.md).

## Features

- Multi-agent workflow (overview → deep dive loop → reading plan)
- GitHub context gathering (repo metadata, tree summary, key file content)
- Budget controls (`--max-cost`, `--max-tokens`)
- JSON or Markdown output
- File output support for CI/reporting (`--output`)

## Installation

### From source (recommended during development)

```bash
pip install -e .
```

Then run:

```bash
repo-brief --help
```

## Requirements

- Python 3.10+
- `OPENAI_API_KEY` environment variable
- Optional: `GITHUB_TOKEN` for higher GitHub API rate limits

You can use a `.env` file:

```env
OPENAI_API_KEY=...
GITHUB_TOKEN=...
```

## Usage

```bash
repo-brief https://github.com/OWNER/REPO
```

### Common options

```bash
repo-brief https://github.com/OWNER/REPO \
  --model gpt-4.1-mini \
  --max-iters 2 \
  --max-turns 12 \
  --max-cost 0.25 \
  --format markdown
```

### JSON output to file

```bash
repo-brief https://github.com/OWNER/REPO \
  --format json \
  --output artifacts/repo-brief.json
```

## Development

Run tests:

```bash
pytest
```

Run quality checks:

```bash
ruff format --check .
ruff check .
mypy
```

Build docs:

```bash
sphinx-build -b html docs docs/_build/html
```

## Notes

- Only public repositories are supported by default.
- If the model emits non-JSON content, the CLI falls back gracefully.
- GitHub and model/API errors are surfaced with non-zero exit codes.
