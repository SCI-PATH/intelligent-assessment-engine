"""Curriculum constants and lookup helpers.

The page-to-chapter mapping is the textbook's Table of Contents and is the
single source of truth used by both the ingest pipeline (to tag chunks) and
the demo UI (to populate the chapter dropdown).

Grades may use one PDF (``pdf:``) or several (``pdfs:`` with ids such as
``part1`` / ``part2``). Chapter page ranges are 1-based **within that file**.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Iterable

import yaml

from iae.domain.models import SubConcept

DEFAULT_GRADE = 6


class UnknownGradeError(KeyError):
    """Raised when a grade is not present in ``curriculum.yaml``."""


class CurriculumConfigError(ValueError):
    """Raised when a grade block is missing PDFs or chapter ``pdf_id``s."""


@dataclass(frozen=True)
class PdfPart:
    id: str
    path: Path


@dataclass(frozen=True)
class ChapterRange:
    name: str
    page_start: int
    page_end: int
    grade: int = DEFAULT_GRADE
    pdf_id: str = "part1"
    pdf_path: Path = Path()

    def contains(self, page: int) -> bool:
        return self.page_start <= page <= self.page_end


@dataclass(frozen=True)
class GradeSpec:
    grade: int
    pdfs: tuple[PdfPart, ...]
    subject: str
    chapters: tuple[ChapterRange, ...]

    @property
    def pdf(self) -> Path:
        """First / only PDF. Prefer ``pdfs`` when a grade has multiple parts."""
        return self.pdfs[0].path


@lru_cache(maxsize=1)
def _load_curriculum_yaml() -> dict:
    raw = files("iae.config").joinpath("curriculum.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(raw) or {}


def _coerce_grade_key(raw_key: object) -> int:
    return int(raw_key)


def _parse_pdfs(block: dict, *, grade: int) -> tuple[PdfPart, ...]:
    raw_pdfs = block.get("pdfs")
    parts: list[PdfPart] = []
    if raw_pdfs:
        for index, item in enumerate(raw_pdfs, start=1):
            default_id = f"part{index}"
            if isinstance(item, str):
                parts.append(PdfPart(id=default_id, path=Path(item)))
                continue
            if not isinstance(item, dict) or not item.get("path"):
                raise CurriculumConfigError(
                    f"Grade {grade} pdfs[{index - 1}] must be a path string or "
                    "{id, path} mapping."
                )
            parts.append(
                PdfPart(
                    id=str(item.get("id") or default_id),
                    path=Path(str(item["path"])),
                )
            )
    elif block.get("pdf"):
        parts.append(PdfPart(id="part1", path=Path(str(block["pdf"]))))

    if not parts:
        raise CurriculumConfigError(
            f"Grade {grade} must declare `pdf:` or `pdfs:` in curriculum.yaml."
        )

    seen: set[str] = set()
    for part in parts:
        if part.id in seen:
            raise CurriculumConfigError(
                f"Grade {grade} has duplicate pdf id {part.id!r}."
            )
        seen.add(part.id)
    return tuple(parts)


def _parse_chapters(
    block: dict,
    *,
    grade: int,
    pdfs: tuple[PdfPart, ...],
) -> tuple[ChapterRange, ...]:
    by_id = {part.id: part for part in pdfs}
    chapters: list[ChapterRange] = []
    for entry in block.get("chapters") or []:
        name = str(entry["name"])
        raw_pdf_id = entry.get("pdf_id")
        if raw_pdf_id:
            pdf_id = str(raw_pdf_id)
        elif len(pdfs) == 1:
            pdf_id = pdfs[0].id
        else:
            raise CurriculumConfigError(
                f"Grade {grade} chapter {name!r} needs pdf_id "
                f"(one of: {', '.join(part.id for part in pdfs)})."
            )
        part = by_id.get(pdf_id)
        if part is None:
            raise CurriculumConfigError(
                f"Grade {grade} chapter {name!r} references unknown pdf_id "
                f"{pdf_id!r}. Known: {', '.join(by_id)}."
            )
        chapters.append(
            ChapterRange(
                name=name,
                page_start=int(entry["page_start"]),
                page_end=int(entry["page_end"]),
                grade=grade,
                pdf_id=part.id,
                pdf_path=part.path,
            )
        )
    return tuple(chapters)


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

    pdfs = _parse_pdfs(block, grade=grade)
    chapters = _parse_chapters(block, grade=grade, pdfs=pdfs)
    return GradeSpec(
        grade=grade,
        pdfs=pdfs,
        subject=str(block.get("subject") or "Science"),
        chapters=chapters,
    )


@lru_cache(maxsize=8)
def get_chapters(grade: int = DEFAULT_GRADE) -> tuple[ChapterRange, ...]:
    return get_grade_spec(grade).chapters


def get_chapter_names(grade: int = DEFAULT_GRADE) -> list[str]:
    return [c.name for c in get_chapters(grade)]


def get_grade_pdf_parts(grade: int = DEFAULT_GRADE) -> tuple[PdfPart, ...]:
    return get_grade_spec(grade).pdfs


def get_grade_pdf_paths(grade: int = DEFAULT_GRADE) -> list[Path]:
    return [part.path for part in get_grade_pdf_parts(grade)]


def get_grade_pdf_path(grade: int = DEFAULT_GRADE) -> Path:
    """First / only PDF for the grade (backward compatible)."""
    return get_grade_spec(grade).pdf


def select_pdf_parts(
    grade: int = DEFAULT_GRADE,
    *,
    pdf_id: str | None = None,
    pdf_path: Path | None = None,
) -> tuple[PdfPart, ...]:
    """Subset of a grade's PDFs, filtered by id and/or path."""
    parts = get_grade_pdf_parts(grade)
    if pdf_id:
        parts = tuple(part for part in parts if part.id == pdf_id)
        if not parts:
            known = ", ".join(p.id for p in get_grade_pdf_parts(grade))
            raise CurriculumConfigError(
                f"Grade {grade} has no pdf_id {pdf_id!r}. Known: {known}."
            )
    if pdf_path is not None:
        wanted = Path(pdf_path)
        parts = tuple(
            part
            for part in parts
            if part.path == wanted
            or part.path.name == wanted.name
            or part.path.resolve() == wanted.resolve()
        )
        if not parts:
            known = ", ".join(str(p.path) for p in get_grade_pdf_parts(grade))
            raise CurriculumConfigError(
                f"{wanted} is not a configured PDF for grade {grade}. Known: {known}."
            )
    return parts


def chapter_for_page(
    page_one_based: int,
    grade: int = DEFAULT_GRADE,
    *,
    pdf_id: str | None = None,
    source: str | Path | None = None,
) -> str | None:
    """Map a 1-based page in a specific PDF to a chapter name."""
    chapters = get_chapters(grade)
    if pdf_id:
        chapters = tuple(c for c in chapters if c.pdf_id == pdf_id)
    elif source is not None:
        source_name = Path(source).name
        chapters = tuple(c for c in chapters if c.pdf_path.name == source_name)
    elif len({c.pdf_id for c in chapters}) > 1:
        raise CurriculumConfigError(
            f"Grade {grade} has multiple PDFs; pass pdf_id or source to "
            "chapter_for_page() so Part 1/Part 2 page numbers do not collide."
        )
    for chapter in chapters:
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
