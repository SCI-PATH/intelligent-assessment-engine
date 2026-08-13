"""Curriculum constants and lookup helpers.

The page-to-chapter mapping is the textbook's Table of Contents and is the
single source of truth used by both the ingest pipeline (to tag chunks) and
the demo UI (to populate the chapter dropdown).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Iterable

import yaml

from iae.core.models import SubConcept

DEFAULT_GRADE = 6


class UnknownGradeError(KeyError):
    """Raised when a grade is not present in ``curriculum.yaml``."""


@dataclass(frozen=True)
class ChapterRange:
    name: str
    page_start: int
    page_end: int
    grade: int = DEFAULT_GRADE

    def contains(self, page: int) -> bool:
        return self.page_start <= page <= self.page_end


@dataclass(frozen=True)
class GradeSpec:
    grade: int
    pdf: Path
    subject: str
    chapters: tuple[ChapterRange, ...]


@lru_cache(maxsize=1)
def _load_curriculum_yaml() -> dict:
    raw = files("iae.config").joinpath("curriculum.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(raw) or {}


def _coerce_grade_key(raw_key: object) -> int:
    return int(raw_key)


def get_available_grades() -> list[int]:
    data = _load_curriculum_yaml()
    return sorted(_coerce_grade_key(key) for key in (data.get("grades") or {}))


def get_grade_spec(grade: int = DEFAULT_GRADE) -> GradeSpec:
    data = _load_curriculum_yaml()
    grades = data.get("grades") or {}
    block = grades.get(grade)
    if block is None:
        block = grades.get(str(grade))
    if block is None:
        raise UnknownGradeError(
            f"Grade {grade} is not defined in curriculum.yaml. "
            f"Available: {get_available_grades()}"
        )

    chapters = tuple(
        ChapterRange(
            name=c["name"],
            page_start=int(c["page_start"]),
            page_end=int(c["page_end"]),
            grade=grade,
        )
        for c in (block.get("chapters") or [])
    )
    return GradeSpec(
        grade=grade,
        pdf=Path(block["pdf"]),
        subject=str(block.get("subject") or "Science"),
        chapters=chapters,
    )


@lru_cache(maxsize=8)
def get_chapters(grade: int = DEFAULT_GRADE) -> tuple[ChapterRange, ...]:
    return get_grade_spec(grade).chapters


def get_chapter_names(grade: int = DEFAULT_GRADE) -> list[str]:
    return [c.name for c in get_chapters(grade)]


def get_grade_pdf_path(grade: int = DEFAULT_GRADE) -> Path:
    return get_grade_spec(grade).pdf


def chapter_for_page(page_one_based: int, grade: int = DEFAULT_GRADE) -> str | None:
    for chapter in get_chapters(grade):
        if chapter.contains(page_one_based):
            return chapter.name
    return None


@lru_cache(maxsize=1)
def get_subconcepts() -> tuple[SubConcept, ...]:
    """Read the curated sub-concept manifest.

    The manifest is generated once via `scripts/extract_subconcepts.py` and
    then hand-reviewed; the live application treats it as read-only data.
    Missing ``grade`` values are treated as Grade 6.
    """
    try:
        raw = files("iae.config").joinpath("subconcepts.yaml").read_text(encoding="utf-8")
    except FileNotFoundError:
        return tuple()
    data = yaml.safe_load(raw) or {}
    entries: list[SubConcept] = []
    for entry in data.get("subconcepts", []):
        payload = dict(entry)
        payload.setdefault("grade", DEFAULT_GRADE)
        entries.append(SubConcept(**payload))
    return tuple(entries)


def subconcepts_for_chapter(
    chapter_name: str,
    grade: int = DEFAULT_GRADE,
) -> list[SubConcept]:
    return [
        s
        for s in get_subconcepts()
        if s.chapter_name == chapter_name and s.grade == grade
    ]


def iter_subconcepts(
    chapters: Iterable[str] | None = None,
    grade: int = DEFAULT_GRADE,
) -> Iterable[SubConcept]:
    wanted = set(chapters) if chapters else None
    for sc in get_subconcepts():
        if sc.grade != grade:
            continue
        if wanted is None or sc.chapter_name in wanted:
            yield sc
