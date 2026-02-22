"""Public package metadata for :mod:`repo_brief`."""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("repo-brief")
except PackageNotFoundError:
    # Editable/dev contexts may not have package metadata available.
    __version__ = "0.0.0"
