Usage
=====

Overview
--------

``repo-brief`` fetches GitHub repo metadata, tree structure, and key files, then runs a multi-stage agent flow:

1. Overview briefing
2. Deep-dive refinement loop
3. Reading plan generation

Installation
------------

.. code-block:: bash

   pip install -e .[dev]

Environment variables
---------------------

- ``OPENAI_API_KEY`` (required)
- ``GITHUB_TOKEN`` (optional, recommended)

GitHub API requests are rate-limited. Providing ``GITHUB_TOKEN`` increases your limit.

Run the CLI
-----------

.. code-block:: bash

   repo-brief https://github.com/OWNER/REPO

Useful options
--------------

- ``--model``: OpenAI model name.
- ``--max-iters``: Number of deep-dive passes.
- ``--max-turns``: Max turns per agent run.
- ``--max-cost`` and ``--max-tokens``: Budget guards.
- ``--format``: ``markdown`` or ``json`` output.
- ``--output``: Write output to a file.

Context-size controls
---------------------

Use these to tune how much repository context is fetched before agent orchestration:

- ``--max-readme-chars`` (default ``12000``): Maximum README characters in context.
- ``--max-tree-entries`` (default ``350``): Maximum repository tree paths in summary output.
- ``--max-key-files`` (default ``12``): Maximum number of representative files sampled.
- ``--max-file-chars`` (default ``12000``): Maximum content characters captured per sampled file.

JSON output example
-------------------

.. code-block:: bash

   repo-brief https://github.com/OWNER/REPO \
     --format json \
     --output artifacts/repo-brief.json
