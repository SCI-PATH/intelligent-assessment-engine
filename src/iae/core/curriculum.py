"""Curriculum constants and lookup helpers.

The page-to-chapter mapping is the textbook's Table of Contents and is the
single source of truth used by both the ingest pipeline (to tag chunks) and
the demo UI (to populate the chapter dropdown).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Iterable

import yaml

from iae.core.models import SubConcept


@dataclass(frozen=True)
class ChapterRange:
    name: str
    page_start: int
    page_end: int

    def contains(self, page: int) -> bool:
        return self.page_start <= page <= self.page_end


@lru_cache(maxsize=1)
def _load_curriculum_yaml() -> dict:
    raw = files("iae.config").joinpath("curriculum.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(raw)


@lru_cache(maxsize=1)
def get_chapters() -> tuple[ChapterRange, ...]:
    data = _load_curriculum_yaml()
    return tuple(
        ChapterRange(name=c["name"], page_start=c["page_start"], page_end=c["page_end"])
        for c in data["chapters"]
    )


def get_chapter_names() -> list[str]:
    return [c.name for c in get_chapters()]


def chapter_for_page(page_one_based: int) -> str | None:
    for chapter in get_chapters():
        if chapter.contains(page_one_based):
            return chapter.name
    return None


@lru_cache(maxsize=1)
def get_subconcepts() -> tuple[SubConcept, ...]:
    """Read the curated sub-concept manifest.

    The manifest is generated once via `scripts/extract_subconcepts.py` and
    then hand-reviewed; the live application treats it as read-only data.
    """
    try:
        raw = files("iae.config").joinpath("subconcepts.yaml").read_text(encoding="utf-8")
    except FileNotFoundError:
        return tuple()
    data = yaml.safe_load(raw) or {}
    return tuple(SubConcept(**entry) for entry in data.get("subconcepts", []))


def subconcepts_for_chapter(chapter_name: str) -> list[SubConcept]:
    return [s for s in get_subconcepts() if s.chapter_name == chapter_name]


def iter_subconcepts(chapters: Iterable[str] | None = None) -> Iterable[SubConcept]:
    wanted = set(chapters) if chapters else None
    for sc in get_subconcepts():
        if wanted is None or sc.chapter_name in wanted:
            yield sc
