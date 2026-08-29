"""Smoke: post-lesson chapter always comes from live C1 (game chapter_id ignored).

Does NOT hit Postgres / C4. Uses a fake Component1Client.

Cases:
  1. omit chapter_id → live C1 chapter (G7_C1)
  2. body G7_C8 stub → still live C1 (G7_C1), not C8
  3. body G7_C3 (would have been trusted) → still live C1 (G7_C1)
  4. C1 down / fallback → ChapterResolveError (no silent G7_C8)
"""

from __future__ import annotations

import sys
from typing import Any

from scripts._path import ensure_src_on_path

ensure_src_on_path()

from iae.application.quiz_service import (
    ChapterResolveError,
    QuizService,
    _is_client_fallback_chapter_id,
)


class _FakeC1:
    def __init__(self, *, response: dict[str, Any] | None = None, raise_on_call: bool = False) -> None:
        self.response = response
        self.raise_on_call = raise_on_call
        self.calls: list[dict[str, Any]] = []

    def fetch_active_chapter(self, *, student_id: str, grade: int | None = None) -> dict[str, Any]:
        self.calls.append({"student_id": student_id, "grade": grade})
        if self.raise_on_call:
            raise RuntimeError("C1 simulated outage")
        assert self.response is not None
        return dict(self.response)


def _svc(c1: _FakeC1) -> QuizService:
    return QuizService(
        sessions=None,  # type: ignore[arg-type]
        questions=None,  # type: ignore[arg-type]
        grading=None,  # type: ignore[arg-type]
        c1=c1,  # type: ignore[arg-type]
    )


def main() -> int:
    assert _is_client_fallback_chapter_id("G7_C8", grade=7)
    assert _is_client_fallback_chapter_id("g7_c8")
    assert not _is_client_fallback_chapter_id("G7_C2", grade=7)
    assert not _is_client_fallback_chapter_id(None)

    live = {
        "ok": True,
        "source": "component_1",
        "student_id": "stu-7",
        "chapter_id": "G7_C1",
        "grade": 7,
        "lesson_id": "g7_sci_01",
    }
    live9 = {
        "ok": True,
        "source": "component_1",
        "student_id": "stu-9",
        "chapter_id": "G9_C6",
        "grade": 9,
        "lesson_id": "g9_sci_06",
    }
    fallback = {
        "ok": True,
        "source": "fallback",
        "student_id": "stu-7",
        "chapter_id": "G7_C8",
        "grade": 7,
        "lesson_id": None,
        "error": "connection refused",
    }

    c1 = _FakeC1(response=live)
    r = _svc(c1).resolve_post_lesson_chapter(student_id="stu-7", chapter_id=None, grade=7)
    assert r["chapter_id"] == "G7_C1", r
    assert r["source"] == "component_1", r
    assert r["lesson_id"] == "g7_sci_01", r
    assert len(c1.calls) == 1
    print("OK omit ->", r["chapter_id"], r["source"])

    c1 = _FakeC1(response=live)
    r = _svc(c1).resolve_post_lesson_chapter(student_id="stu-7", chapter_id="G7_C8", grade=7)
    assert r["chapter_id"] == "G7_C1", r
    assert r["source"] == "component_1", r
    assert r["chapter_id"] != "G7_C8"
    assert len(c1.calls) == 1
    print("OK stub G7_C8 ignored ->", r["chapter_id"], r["source"])

    c1 = _FakeC1(response=live)
    r = _svc(c1).resolve_post_lesson_chapter(student_id="stu-7", chapter_id="G7_C3", grade=7)
    assert r["chapter_id"] == "G7_C1", r
    assert r["source"] == "component_1", r
    assert len(c1.calls) == 1
    print("OK body G7_C3 ignored ->", r["chapter_id"], r["source"], "(C1 always used)")

    c1 = _FakeC1(response=live9)
    r = _svc(c1).resolve_post_lesson_chapter(student_id="stu-9", chapter_id=None, grade=9)
    assert r["chapter_id"] == "G9_C6", r
    assert r["grade"] == 9, r
    print("OK grade 9 ->", r["chapter_id"], r["source"])

    c1 = _FakeC1(response=fallback)
    try:
        _svc(c1).resolve_post_lesson_chapter(student_id="stu-7", chapter_id="G7_C8", grade=7)
        raise AssertionError("expected ChapterResolveError on C1 fallback")
    except ChapterResolveError as exc:
        assert "Component 1" in str(exc)
        print("OK C1 down raises (no G7_C8) ->", type(exc).__name__)

    c1 = _FakeC1(response=fallback)
    try:
        _svc(c1).resolve_post_lesson_chapter(student_id="stu-7", chapter_id=None, grade=7)
        raise AssertionError("expected ChapterResolveError when chapter omitted and C1 down")
    except ChapterResolveError:
        print("OK omit + C1 down raises")

    print("POST_LESSON_CHAPTER_RESOLVE_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print("FAIL", exc, file=sys.stderr)
        raise SystemExit(1) from exc
