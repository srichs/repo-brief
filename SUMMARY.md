# repo-brief: 80% Understanding Overview

## What it is / Who it's for
`repo-brief` is an agentic command-line utility for software engineers, tech leads, and researchers who need fast, high-signal onboarding into public GitHub repositories.

## Key Features (Supported by Files)
- **Multi-agent workflow:** Generates an overview, optional deep-dive iterations, and a reading plan.
- **CLI-first usage:** Exposes `repo-brief` as a console script with configurable model, budget, and context limits.
- **Structured outputs:** Supports markdown and JSON outputs plus optional file output.
- **Budget-aware execution:** Tracks tokens/cost and can stop when configured limits are reached.
- **GitHub context ingestion:** Pulls metadata, tree summary, and sampled file contents from the target repository.

## Architecture Overview (Directly Evidenced)
- **CLI + orchestration entrypoint:** `src/repo_brief/cli.py` wires argument parsing, validation, and orchestration.
- **Agent orchestration:** `src/repo_brief/agents_workflow.py` defines agents, parsing helpers, and the briefing loop.
- **GitHub data access:** `src/repo_brief/github_client.py` handles API requests, tree/file retrieval, and context shaping.
- **Cost accounting:** `src/repo_brief/budget.py` computes usage totals and estimated cost.

## Execution Model / Entrypoints
- Console command: `repo-brief https://github.com/OWNER/REPO`
- Module execution: `python -m repo_brief`
- Entrypoint function: `main()` in `src/repo_brief/cli.py`

## Suggested first 3 files to read
1. `src/repo_brief/cli.py`
2. `src/repo_brief/agents_workflow.py`
3. `src/repo_brief/github_client.py`

## Open questions
- How should providers/models beyond the default stack be configured for production use?
- Should repository context sampling become pluggable by language/ecosystem?
- What additional reliability checks should run before each agent stage?

---

# Reading Plan (Get Productive Fast)

1. **README.md**  
   Understand product scope, install/run flow, and expected outputs.

2. **src/repo_brief/cli.py**  
   Learn argument parsing, runtime guards, and output rendering.

3. **src/repo_brief/agents_workflow.py**  
   Study the overview/deep-dive/reading-plan loop and response parsing.

4. **src/repo_brief/github_client.py**  
   Review repository fetch mechanics and context assembly.

5. **src/repo_brief/budget.py**  
   Confirm how token usage and cost ceilings are calculated/enforced.

6. **tests/test_repo_brief_utils.py**  
   Use tests to see expected behavior and edge cases.

7. **pyproject.toml** and **.github/workflows/ci.yml**  
   Verify tooling standards and CI checks (`ruff`, `mypy`, `pytest`).
