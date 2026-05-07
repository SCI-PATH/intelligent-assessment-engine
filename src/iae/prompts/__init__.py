"""Prompt asset loader.

Templates are plain Jinja files committed to source control so prompt edits
show up clearly in version history without rebuilding Python code.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from jinja2 import Environment, StrictUndefined


@lru_cache(maxsize=None)
def _load_raw(relative_path: str) -> str:
    return files("iae.prompts").joinpath(relative_path).read_text(encoding="utf-8")


def render(relative_path: str, **context) -> str:
    template_source = _load_raw(relative_path)
    env = Environment(undefined=StrictUndefined, autoescape=False)
    return env.from_string(template_source).render(**context)
