"""CLI package. Puts ``src/`` on ``sys.path`` before submodule imports run."""

from ._path import ensure_src_on_path

ensure_src_on_path()
