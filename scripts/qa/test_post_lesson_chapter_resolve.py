"""Smoke: post-lesson chapter resolution prefers live C1 over Game G*_C8 stub.

Does NOT hit Postgres / C4. Uses a fake Component1Client.

Cases:
  1. omit chapter_id → live C1 chapter (G7_C2)
  2. body G7_C8 + live C1 progress → G7_C2 (not C8)
  3. C1 down / fallback → grade-aware G7_C8 only
  4. trusted explicit G7_C3 → request wins (C1 not consulted)
"""

from __future__ import annotations

import sys
from typing import Any

from scripts._path import ensure_src_on_path

ensure_src_on_path()

from iae.application.quiz_service import QuizService, _is_client_fallback_chapter_id


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
    # Repos unused by resolve_post_lesson_chapter.
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
        "chapter_id": "G7_C2",
        "grade": 7,
        "lesson_id": "g7_sci_02",
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

    # 1) omit chapter_id → live C1
    c1 = _FakeC1(response=live)
    r = _svc(c1).resolve_post_lesson_chapter(student_id="stu-7", chapter_id=None, grade=7)
    assert r["chapter_id"] == "G7_C2", r
    assert r["source"] == "component_1", r
    assert r["lesson_id"] == "g7_sci_02", r
    assert len(c1.calls) == 1
    print("OK omit ->", r["chapter_id"], r["source"])

    # 2) Game stub G7_C8 → still live C1 chapter
    c1 = _FakeC1(response=live)
    r = _svc(c1).resolve_post_lesson_chapter(student_id="stu-7", chapter_id="G7_C8", grade=7)
    assert r["chapter_id"] == "G7_C2", r
    assert r["source"] == "component_1", r
    assert r["chapter_id"] != "G7_C8"
    assert len(c1.calls) == 1
    print("OK stub G7_C8 ->", r["chapter_id"], r["source"])

    # 3) C1 down → grade-aware fallback only
    c1 = _FakeC1(response=fallback)
    r = _svc(c1).resolve_post_lesson_chapter(student_id="stu-7", chapter_id="G7_C8", grade=7)
    assert r["chapter_id"] == "G7_C8", r
    assert r["source"] == "fallback", r
    print("OK C1 down ->", r["chapter_id"], r["source"])

    c1 = _FakeC1(response=fallback)
    r = _svc(c1).resolve_post_lesson_chapter(student_id="stu-7", chapter_id=None, grade=7)
    assert r["chapter_id"] == "G7_C8", r
    assert r["source"] == "fallback", r
    print("OK omit + C1 down ->", r["chapter_id"], r["source"])

    # 4) trusted explicit chapter skips C1
    c1 = _FakeC1(response=live)
    r = _svc(c1).resolve_post_lesson_chapter(student_id="stu-7", chapter_id="G7_C3", grade=7)
    assert r["chapter_id"] == "G7_C3", r
    assert r["source"] == "request", r
    assert c1.calls == []
    print("OK trusted G7_C3 ->", r["chapter_id"], r["source"], "(C1 skipped)")

    print("POST_LESSON_CHAPTER_RESOLVE_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print("FAIL", exc, file=sys.stderr)
        raise SystemExit(1) from exc
