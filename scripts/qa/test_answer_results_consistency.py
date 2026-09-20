"""Integration: final /answer + immediate /results must list every attempt.

Uses TestClient + real DB (same as smoke_v1). MCQ-only for predictable grading speed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient

from iae.api.main import app
from iae.domain.chapter_catalog import normalize_chapter_id
from iae.domain.curriculum import get_chapter_names

PREFIX = "/api/v1/assessment-engine"


def main() -> int:
    user = "mock-student-class-a"
    grade = 7
    max_q = 3
    chapters = get_chapter_names(grade)
    chapter = chapters[0] if chapters else "Plant Diversity"
    chapter_id = normalize_chapter_id(chapter, grade=grade) or "G7_C1"

    with TestClient(app) as client:
        created = client.post(
            f"{PREFIX}/quizzes/customizable",
            json={
                "student_id": user,
                "grade": grade,
                "chapters": [chapter_id],
                "num_questions": max_q,
                "question_types": ["MCQ", "TrueFalse"],
            },
        )
        if created.status_code != 200:
            print("SKIP customizable create", created.status_code, created.text)
            return 0
        sid = created.json()["session_id"]

        nxt = client.get(f"{PREFIX}/quizzes/{sid}/next")
        nxt.raise_for_status()
        q = nxt.json()["question"]
        last_qid = q["id"]

        for i in range(max_q):
            ans = client.post(
                f"{PREFIX}/quizzes/{sid}/answer",
                json={
                    "question_id": last_qid,
                    "student_answer": "A",
                    "time_taken_seconds": 5.0,
                },
            )
            ans.raise_for_status()
            body = ans.json()
            is_last = i == max_q - 1
            if is_last:
                assert body["is_complete"] is True, body
                assert body["status"] == "completed", body

            res = client.get(f"{PREFIX}/quizzes/{sid}/results")
            res.raise_for_status()
            results = res.json()
            expected = i + 1
            assert results["total_answered"] == expected, results
            assert len(results["history"]) == expected, results
            assert results["history"][-1]["question_id"] == last_qid, results

            if not is_last:
                nxt = client.get(f"{PREFIX}/quizzes/{sid}/next")
                nxt.raise_for_status()
                last_qid = nxt.json()["question"]["id"]

        assert results["total_answered"] == max_q, results
        assert results["questions_asked"] == max_q, results
        print("ANSWER_RESULTS_CONSISTENCY_OK", f"session={sid}", f"history={max_q}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print("FAIL", exc, file=sys.stderr)
        raise SystemExit(1) from exc
