"""Sphinx configuration for the repo-brief documentation site."""

from __future__ import annotations

from datetime import datetime
from importlib.metadata import PackageNotFoundError, version

from repo_brief import __version__

project = "repo-brief"
author = "repo-brief contributors"
copyright = f"{datetime.now().year}, {author}"
try:
    release = version("repo-brief")
except PackageNotFoundError:
    release = __version__

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "furo"
html_static_path = ["_static"]

autodoc_typehints = "description"
