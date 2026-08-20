"""Smoke test for /api/v1 happy paths (Amplitude, quiz, terminate, history)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient

from iae.api.main import app
from iae.core.curriculum import get_chapter_names


def main() -> int:
    with TestClient(app) as client:
        return _run(client)


def _run(client: TestClient) -> int:
    user = "mock-student-class-a"
    grade = 7
    chapters = get_chapter_names(grade)
    chapter = chapters[0] if chapters else "Magnets"
    # Prefer canonical chapter_id when catalog is available
    from iae.core.chapter_catalog import normalize_chapter_id

    chapter_id = normalize_chapter_id(chapter, grade=grade) or "G7_C1"

    r = client.post(
        "/api/v1/amplitude/survey",
        json={
            "user_id": user,
            "grade": grade,
            "completed_chapters_count": 3,
            "past_grade_marks_range": "50_75",
            "study_hours_per_week": 4,
            "self_confidence": 3,
        },
    )
    print("survey", r.status_code)
    r.raise_for_status()

    quiz = client.get("/api/v1/amplitude/quiz", params={"grade": grade})
    print("quiz", quiz.status_code, "count", quiz.json().get("count"))
    quiz.raise_for_status()
    answers = {item["id"]: "A" for item in quiz.json().get("questions", [])}
    ev = client.post(
        "/api/v1/amplitude/evaluate",
        json={
            "user_id": user,
            "grade": grade,
            "completed_chapters_count": 3,
            "past_grade_marks_range": "50_75",
            "study_hours_per_week": 4,
            "self_confidence": 3,
            "answers": answers,
        },
    )
    print("evaluate", ev.status_code, ev.json().get("category"))
    ev.raise_for_status()

    cat = client.get(f"/api/v1/student/{user}/initial-category")
    print("initial-category", cat.status_code, cat.json())
    cat.raise_for_status()

    created = client.post(
        "/api/v1/quizzes/customizable",
        json={
            "student_id": user,
            "grade": grade,
            "chapters": [chapter_id],
            "num_questions": 2,
        },
    )
    print("customizable", created.status_code)
    created.raise_for_status()
    sid = created.json()["session_id"]

    nxt = client.get(f"/api/v1/quizzes/{sid}/next")
    print("next", nxt.status_code)
    if nxt.status_code == 200:
        qid = nxt.json()["question"]["id"]
        ans = client.post(
            f"/api/v1/quizzes/{sid}/answer",
            json={"question_id": qid, "student_answer": "A", "time_taken_seconds": 12},
        )
        print("answer", ans.status_code, ans.json().get("status"))
        ans.raise_for_status()

    term = client.post(
        f"/api/v1/quiz/{sid}/terminate",
        json={"reason": "smoke_test", "source": "component_3"},
    )
    print("terminate", term.status_code, term.json().get("status"))
    term.raise_for_status()

    hist = client.get(f"/api/v1/student/{user}/sessions")
    print("history", hist.status_code, "n=", len(hist.json()))
    hist.raise_for_status()

    post = client.post(
        "/api/v1/quiz/trigger-post-lesson",
        json={"student_id": user, "chapter_id": chapter_id, "grade": grade},
    )
    print("post-lesson", post.status_code, "max=", post.json().get("max_questions"))
    post.raise_for_status()
    assert post.json()["max_questions"] == 15

    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
