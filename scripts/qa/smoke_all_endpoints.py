"""Exercise every Swagger / OpenAPI inbound endpoint (Component 2).

Usage
-----
    python -m scripts.qa.smoke_all_endpoints

Uses TestClient lifespan (same wiring as /docs). Does not open a browser;
prints PASS/FAIL per route so you can compare with Swagger Try-it-out.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient

from iae.api.main import app
from iae.domain.models import (
    QuestionType,
    RejectionReason,
    TrueFalsePayload,
)

PREFIX = "/api/v1/assessment-engine"
RESULTS: list[tuple[str, str, int, str]] = []


def _record(name: str, method: str, status: int, note: str = "") -> None:
    flag = "PASS" if 200 <= status < 300 else "FAIL"
    RESULTS.append((flag, method, status, f"{name} {note}".strip()))
    print(f"[{flag}] {method:6} {status}  {name} {note}".rstrip())


def main() -> int:
    with TestClient(app) as client:
        # --- Health ---
        r = client.get("/")
        _record("GET /", "GET", r.status_code)

        # --- Aptitude ---
        r = client.get(f"{PREFIX}/amplitude/chapters", params={"grade": 7})
        _record("amplitude/chapters", "GET", r.status_code, f"count={r.json().get('count')}")

        r = client.post(
            f"{PREFIX}/amplitude/survey",
            json={
                "user_id": "mock-student-class-a",
                "grade": 7,
                "completed_chapter_ids": [],
                "past_grade_marks_range": "50_75",
                "study_hours_per_week": 5.0,
                "self_confidence": 3,
                "science_self_efficacy": 4,
                "prerequisite_ready_count": 3,
            },
        )
        _record("amplitude/survey", "POST", r.status_code)

        for grade in (6, 7, 8, 9):
            r = client.get(f"{PREFIX}/amplitude/quiz", params={"grade": grade})
            _record(
                f"amplitude/quiz?grade={grade}",
                "GET",
                r.status_code,
                f"count={r.json().get('count')}" if r.status_code == 200 else r.text[:60],
            )

        quiz = client.get(f"{PREFIX}/amplitude/quiz", params={"grade": 7}).json()
        answers = {item["id"]: "A" for item in quiz.get("questions", [])}
        r = client.post(
            f"{PREFIX}/amplitude/evaluate",
            json={
                "user_id": "mock-student-class-a",
                "grade": 7,
                "completed_chapter_ids": [],
                "past_grade_marks_range": "50_75",
                "study_hours_per_week": 5.0,
                "self_confidence": 3,
                "science_self_efficacy": 4,
                "prerequisite_ready_count": 3,
                "answers": answers,
            },
        )
        cat = r.json().get("category") if r.status_code == 200 else ""
        _record("amplitude/evaluate", "POST", r.status_code, str(cat))

        r = client.get(f"{PREFIX}/students/mock-student-class-a/initial-category")
        _record("students/.../initial-category", "GET", r.status_code, str(r.json()))

        # --- Customizable quiz loop ---
        r = client.post(
            f"{PREFIX}/quizzes/customizable",
            json={
                "student_id": "mock-student-class-a",
                "grade": 6,
                "chapters": ["G6_C8", "G6_C7"],
                "num_questions": 2,
                "question_types": ["MCQ", "TrueFalse"],
            },
        )
        _record("quizzes/customizable", "POST", r.status_code)
        session_id = r.json().get("session_id") if r.status_code == 200 else None

        if session_id:
            r = client.get(f"{PREFIX}/quizzes/{session_id}/next")
            _record("quizzes/{id}/next", "GET", r.status_code)
            if r.status_code == 200:
                q = r.json().get("question") or {}
                qid = q.get("id")
                payload = q.get("payload") or {}
                ans = "A"
                if q.get("question_type") == "TrueFalse":
                    ans = str(payload.get("correct_answer") or "True")
                elif payload.get("correct_answer"):
                    ans = str(payload["correct_answer"])
                r = client.post(
                    f"{PREFIX}/quizzes/{session_id}/answer",
                    json={
                        "question_id": qid,
                        "student_answer": ans,
                        "time_taken_seconds": 15.0,
                    },
                )
                _record("quizzes/{id}/answer", "POST", r.status_code)

            r = client.get(f"{PREFIX}/quizzes/{session_id}/results")
            _record("quizzes/{id}/results", "GET", r.status_code)

            r = client.get(f"{PREFIX}/students/mock-student-class-a/sessions")
            _record("students/.../sessions", "GET", r.status_code, f"n={len(r.json()) if r.status_code==200 else 0}")

            r = client.get(f"{PREFIX}/students/mock-student-class-a/sessions/{session_id}")
            _record("students/.../sessions/{id}", "GET", r.status_code)

            # Analyze may call LLM — accept 200 or soft fail note
            r = client.post(
                f"{PREFIX}/students/mock-student-class-a/sessions/{session_id}/analyze"
            )
            note = ""
            if r.status_code >= 400:
                note = r.text[:80]
            _record("students/.../sessions/{id}/analyze", "POST", r.status_code, note)

        # --- Post-lesson + terminate ---
        r = client.post(
            f"{PREFIX}/quizzes/post-lesson",
            json={
                "student_id": "mock-student-class-a",
                "chapter_id": "G6_C8",
                "grade": 6,
            },
        )
        _record("quizzes/post-lesson", "POST", r.status_code)
        pl_id = r.json().get("session_id") if r.status_code == 200 else None
        if pl_id:
            r = client.post(
                f"{PREFIX}/quizzes/{pl_id}/terminate",
                json={"reason": "frustration_threshold", "source": "component_3"},
            )
            _record("quizzes/{id}/terminate", "POST", r.status_code)

        # --- Teacher ---
        r = client.get(f"{PREFIX}/teacher/topics", params={"grade": 6})
        n_topics = len((r.json() or {}).get("topics") or []) if r.status_code == 200 else 0
        _record("teacher/topics", "GET", r.status_code, f"n={n_topics}")

        r = client.get(
            f"{PREFIX}/teacher/questions",
            params={"grade": 6, "status": "approved", "limit": 5},
        )
        n_q = len((r.json() or {}).get("questions") or []) if r.status_code == 200 else 0
        _record("teacher/questions", "GET", r.status_code, f"n={n_q}")

        custom_body = {
            "grade": 6,
            "chapter_name": "Magnets",
            "topic_id": "G6_C7_MAG_POLES",
            "skill": "Magnetic poles",
            "dok_level": 1,
            "question_type": "TrueFalse",
            "sub_concept": "Poles",
            "payload": {
                "type": "TrueFalse",
                "question": f"Swagger smoke TF {uuid4().hex[:6]}: unlike poles attract.",
                "correct_answer": "True",
                "distractor_tag": "MISCONCEPTION",
                "distractor_label": "Believes like poles attract",
            },
        }
        r = client.post(f"{PREFIX}/teacher/questions", json=custom_body)
        _record("teacher/questions (create)", "POST", r.status_code)
        new_id = r.json().get("id") if r.status_code == 200 else None

        if new_id:
            r = client.post(f"{PREFIX}/teacher/questions/{new_id}/approve")
            _record("teacher/questions/{id}/approve", "POST", r.status_code)
            # create another to reject
            custom_body["payload"]["question"] = f"Reject smoke TF {uuid4().hex[:6]}"
            r2 = client.post(f"{PREFIX}/teacher/questions", json=custom_body)
            rid = r2.json().get("id") if r2.status_code == 200 else None
            if rid:
                r = client.post(
                    f"{PREFIX}/teacher/questions/{rid}/reject",
                    json={
                        "reason": "POOR_PHRASING",
                        "notes": "Stem is ambiguous for Grade 6.",
                    },
                )
                _record("teacher/questions/{id}/reject", "POST", r.status_code)

        # Generate hits LLM — may be slow; still exercise the route
        r = client.post(
            f"{PREFIX}/teacher/generate",
            json={
                "topic_id": "G6_C7_MAG_POLES",
                "dok_level": 1,
                "question_type": "MCQ",
                "count": 1,
            },
        )
        note = ""
        if r.status_code >= 400:
            note = r.text[:100]
        elif r.status_code == 200:
            note = f"created={r.json().get('created')}"
        _record("teacher/generate", "POST", r.status_code, note)

        # OpenAPI has examples for survey
        schema = client.app.openapi()["components"]["schemas"].get("AmplitudeSurveyRequest", {})
        has_ex = bool(schema.get("examples") or schema.get("example"))
        print(f"[INFO] AmplitudeSurveyRequest has OpenAPI examples: {has_ex}")

    fails = [row for row in RESULTS if row[0] == "FAIL"]
    print("---")
    print(f"Total {len(RESULTS)} checks, {len(fails)} FAIL")
    if fails:
        for row in fails:
            print(" ", row)
        return 1
    print("SMOKE_ALL_ENDPOINTS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
