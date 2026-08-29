"""Mapper: C1 /progress JSON → canonical G7_C1 / G9_C6 (no live HTTP)."""

from __future__ import annotations

import sys

from scripts._path import ensure_src_on_path

ensure_src_on_path()

from iae.infrastructure.clients.peers import _map_c1_progress_to_chapter


def _assert_map(data: dict, expected_cid: str, expected_grade: int) -> None:
    mapped = _map_c1_progress_to_chapter(data)
    assert mapped is not None, f"map failed for {data}"
    cid, grade, _lesson = mapped
    assert cid == expected_cid, (cid, data)
    assert grade == expected_grade, (grade, data)


def main() -> int:
    _assert_map(
        {
            "grade": 7,
            "current_lesson_id": "g7_sci_01",
            "completed_lesson_ids": ["g7_sci_01", "g7_sci_03", "g7_sci_02"],
        },
        "G7_C1",
        7,
    )
    _assert_map(
        {"grade": 9, "current_lesson_id": "g9_sci_06"},
        "G9_C6",
        9,
    )
    _assert_map(
        {"grade": 7, "chapter_number": 1},
        "G7_C1",
        7,
    )
    _assert_map(
        {"grade": 9, "chapter": 6},
        "G9_C6",
        9,
    )
    _assert_map(
        {"grade": 7, "chapter_id": "G7_C1"},
        "G7_C1",
        7,
    )
    _assert_map(
        {"grade": 7, "lesson_id": "g7_sci_01"},
        "G7_C1",
        7,
    )
    _assert_map(
        {"grade": 9, "chapter_id": "G9_C6_CIR_HEART"},
        "G9_C6",
        9,
    )
    # Current lesson wins over last completed.
    _assert_map(
        {
            "grade": 7,
            "current_lesson_id": "g7_sci_01",
            "completed_lesson_ids": ["g7_sci_02"],
        },
        "G7_C1",
        7,
    )
    assert _map_c1_progress_to_chapter({"grade": 7}) is None
    print("C1_PROGRESS_MAP_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print("FAIL", exc, file=sys.stderr)
        raise SystemExit(1) from exc
