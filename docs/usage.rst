Usage
=====

Installation
------------

.. code-block:: bash

   pip install -e .[dev]

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
