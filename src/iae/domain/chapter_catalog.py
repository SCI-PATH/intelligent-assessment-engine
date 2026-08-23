"""Canonical chapter_id catalog (Component 4 shared IDs).

Source file: ``data/chapter_ids_g6_g9.csv``
Format: ``G{grade}_C{chapter}`` e.g. ``G6_C8``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class ChapterRecord:
    chapter_id: str
    grade: int
    chapter: int
    chapter_title: str
    topic_ids: tuple[str, ...]


def _csv_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    return root / "data" / "chapter_ids_g6_g9.csv"


@lru_cache(maxsize=1)
def load_chapters() -> dict[str, ChapterRecord]:
    path = _csv_path()
    if not path.is_file():
        return {}
    out: dict[str, ChapterRecord] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            chapter_id = (row.get("chapter_id") or "").strip()
            if not chapter_id:
                continue
            topics = tuple(
                t
                for key in ("topic_id_1", "topic_id_2")
                if (t := (row.get(key) or "").strip())
            )
            out[chapter_id] = ChapterRecord(
                chapter_id=chapter_id,
                grade=int(row["grade"]),
                chapter=int(row["chapter"]),
                chapter_title=(row.get("chapter_title") or "").strip(),
                topic_ids=topics,
            )
    return out


def get_chapter(chapter_id: str) -> ChapterRecord | None:
    return load_chapters().get(chapter_id.strip())


def chapters_for_grade(grade: int) -> list[ChapterRecord]:
    """All catalog chapters for a grade, ordered by chapter number."""
    rows = [r for r in load_chapters().values() if r.grade == grade]
    rows.sort(key=lambda r: r.chapter)
    return rows


def chapter_count_for_grade(grade: int) -> int:
    return len(chapters_for_grade(grade))


def normalize_chapter_id(raw: str, *, grade: int | None = None) -> str | None:
    """Accept ``G6_C8``, title ``Magnets``, or topic id ``G6_C8_ELE_CIRCUITS``."""
    text = (raw or "").strip()
    if not text:
        return None
    catalog = load_chapters()
    upper = text.upper().replace("-", "_")
    if upper in catalog:
        return upper
    # Full topic id → chapter_id prefix G#_C#
    parts = upper.split("_")
    if len(parts) >= 2 and parts[0].startswith("G") and parts[1].startswith("C"):
        candidate = f"{parts[0]}_{parts[1]}"
        if candidate in catalog:
            return candidate
    # Title match (case-insensitive)
    lowered = text.casefold()
    for record in catalog.values():
        if record.chapter_title.casefold() == lowered:
            if grade is None or record.grade == grade:
                return record.chapter_id
    return None


def chapter_title(chapter_id_or_title: str, *, grade: int | None = None) -> str:
    """Resolve bank ``chapter_name`` (title) from a chapter_id or pass-through title."""
    cid = normalize_chapter_id(chapter_id_or_title, grade=grade)
    if cid:
        record = get_chapter(cid)
        if record:
            return record.chapter_title
    return chapter_id_or_title


def resolve_chapter_ids(raw_chapters: list[str], *, grade: int | None = None) -> list[str]:
    """Map a mix of titles / ids into canonical chapter_id list (deduped, order kept)."""
    resolved: list[str] = []
    for item in raw_chapters:
        cid = normalize_chapter_id(item, grade=grade)
        if cid and cid not in resolved:
            resolved.append(cid)
        elif not cid and item.strip() and item.strip() not in resolved:
            # Keep unknown tokens so callers can surface validation errors.
            resolved.append(item.strip())
    return resolved


def bank_chapter_names(chapter_ids: list[str], *, grade: int | None = None) -> list[str]:
    """Titles used when querying ``question_engine.questions.chapter_name``."""
    return [chapter_title(cid, grade=grade) for cid in chapter_ids]
