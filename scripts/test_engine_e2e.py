"""End-to-end checks against local Postgres + the FastAPI app.

Seeds enough approved Grade 6 items for the placement quiz, then hits
placement, teacher approve, and diagnostic grading for all four question types.

Run with the project venv::

    python -m scripts.test_engine_e2e
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient
from sqlalchemy import text

from iae.api.main import app
from iae.core.models import (
    MCQPayload,
    MultiBlankPayload,
    Question,
    QuestionOrigin,
    QuestionStatus,
    QuestionType,
    ShortAnswerPayload,
    TrueFalsePayload,
)
from iae.core.skills import topics_for_grade
from iae.infrastructure.postgres.engine import get_engine, get_session_factory, init_schema
from iae.infrastructure.postgres.questions_repo import PostgresQuestionRepository

USER_ID = f"e2e-{uuid4().hex[:8]}"
CHAPTER = "Magnets"
GRADE = 6


def _fail(step: str, detail: str) -> None:
    raise AssertionError(f"[{step}] {detail}")


def _seed_bank() -> dict[str, Question]:
    topics = topics_for_grade(GRADE)
    if len(topics) < 10:
        _fail("seed", f"Need 10 Grade {GRADE} Topic IDs in topics.yaml, found {len(topics)}.")
    repo = PostgresQuestionRepository(get_session_factory())
    quiz_items: list[Question] = []
    for index, topic in enumerate(topics[:10]):
        quiz_items.append(
            Question(
                chapter_name=topic.chapter_title or CHAPTER,
                sub_concept=topic.skill,
                dok_level=2,
                question_type=QuestionType.MCQ,
                payload=MCQPayload(
                    question=f"E2E quiz item {index + 1} for {topic.topic_id}?",
                    options={"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"},
                    correct_answer="A",
                ),
                grade=GRADE,
                topic_id=topic.topic_id,
                skill=topic.skill,
                status=QuestionStatus.APPROVED,
                origin=QuestionOrigin.TEACHER,
            )
        )

    typed = {
        "mcq": Question(
            chapter_name=CHAPTER,
            sub_concept="E2E",
            dok_level=2,
            question_type=QuestionType.MCQ,
            payload=MCQPayload(
                question="Which pole of a bar magnet seeks geographic north?",
                options={
                    "A": "North pole",
                    "B": "South pole",
                    "C": "Equator",
                    "D": "Unrelated metal scrap",
                },
                correct_answer="A",
            ),
            grade=GRADE,
            topic_id="G6_C7_MAG_POLES",
            skill="E2E MCQ",
            status=QuestionStatus.APPROVED,
            origin=QuestionOrigin.TEACHER,
        ),
        "sa": Question(
            chapter_name=CHAPTER,
            sub_concept="E2E",
            dok_level=2,
            question_type=QuestionType.SHORT_ANSWER,
            payload=ShortAnswerPayload(
                question="What does a magnet attract?",
                ideal_answer="A magnet attracts iron",
                keywords=["magnet", "iron"],
            ),
            grade=GRADE,
            topic_id="G6_C7_MAG_POLES",
            skill="E2E SA",
            status=QuestionStatus.APPROVED,
            origin=QuestionOrigin.TEACHER,
        ),
        "mb": Question(
            chapter_name=CHAPTER,
            sub_concept="E2E",
            dok_level=2,
            question_type=QuestionType.MULTI_BLANK,
            payload=MultiBlankPayload(
                paragraph="A ___ attracts ___.",
                answers=["magnet", "iron"],
            ),
            grade=GRADE,
            topic_id="G6_C7_MAG_POLES",
            skill="E2E MultiBlank",
            status=QuestionStatus.APPROVED,
            origin=QuestionOrigin.TEACHER,
        ),
        "tf": Question(
            chapter_name=CHAPTER,
            sub_concept="E2E",
            dok_level=1,
            question_type=QuestionType.TRUE_FALSE,
            payload=TrueFalsePayload(
                question="Like poles of a magnet attract each other.",
                correct_answer="False",
            ),
            grade=GRADE,
            topic_id="G6_C7_MAG_POLES",
            skill="E2E TF",
            status=QuestionStatus.APPROVED,
            origin=QuestionOrigin.TEACHER,
        ),
        "pending": Question(
            chapter_name=CHAPTER,
            sub_concept="E2E",
            dok_level=2,
            question_type=QuestionType.MCQ,
            payload=MCQPayload(
                question="E2E pending item awaiting teacher approve?",
                options={"A": "Yes", "B": "No", "C": "Maybe", "D": "Skip"},
                correct_answer="A",
            ),
            grade=GRADE,
            topic_id="G6_C7_MAG_POLES",
            skill="E2E pending",
            status=QuestionStatus.PENDING,
            origin=QuestionOrigin.AI,
        ),
    }
    repo.insert_many(quiz_items + list(typed.values()))
    return typed


def _assert_db_diagnostics(question_id: str, *, expect_error: bool = False, expect_distractor: bool = False) -> None:
    engine = get_engine()
    with engine.connect() as conn:
        attempt = conn.execute(
            text(
                "SELECT error_category, distractor_tag, distractor_label, missed_blanks, "
                "concept_explanation FROM question_engine.attempts "
                "WHERE question_id = :qid ORDER BY answered_at DESC LIMIT 1"
            ),
            {"qid": question_id},
        ).mappings().first()
        event = conn.execute(
            text(
                "SELECT error_category, distractor_tag, distractor_label, payload "
                "FROM question_engine.analytics_events "
                "WHERE question_id = :qid ORDER BY created_at DESC LIMIT 1"
            ),
            {"qid": question_id},
        ).mappings().first()
    if attempt is None:
        _fail("db.attempts", f"No attempt row for {question_id}")
    if event is None:
        _fail("db.analytics", f"No analytics_events row for {question_id}")
    if expect_error and not attempt["error_category"]:
        _fail("db.attempts", f"Expected error_category on {question_id}")
    if expect_distractor:
        if not attempt["distractor_tag"] or not attempt["distractor_label"]:
            _fail("db.attempts", f"Expected distractor_tag/label on {question_id}")
        if not event["distractor_tag"] or not event["distractor_label"]:
            _fail("db.analytics", f"Expected distractor_tag/label on {question_id}")


def main() -> int:
    print("Initializing schema and seeding Grade 6 bank…")
    init_schema()
    seeded = _seed_bank()
    print(f"  user_id={USER_ID}")

    print("Booting FastAPI TestClient…")
    with TestClient(app, raise_server_exceptions=False) as client:
        health = client.get("/")
        if health.status_code != 200 or health.json().get("status") != "ok":
            _fail("GET /", str(health.text))

        survey = client.post(
            "/assessment/placement/survey",
            json={
                "user_id": USER_ID,
                "grade": GRADE,
                "completed_chapters_count": 3,
                "past_grade_marks_range": "50_75",
            },
        )
        if survey.status_code != 200:
            _fail("POST /assessment/placement/survey", survey.text)
        if survey.json().get("user_id") != USER_ID:
            _fail("POST /assessment/placement/survey", "user_id mismatch")
        print("  survey ok")

        quiz = client.get(f"/assessment/placement/quiz?grade={GRADE}")
        if quiz.status_code != 200:
            _fail("GET /assessment/placement/quiz", quiz.text)
        body = quiz.json()
        if body.get("count") != 10 or len(body.get("questions") or []) != 10:
            _fail("GET /assessment/placement/quiz", f"expected 10 questions, got {body}")
        prompt = body["questions"][0]["prompt"]
        if "correct_answer" in prompt or "ideal_answer" in prompt:
            _fail("GET /assessment/placement/quiz", "quiz leaked answer keys")
        print("  quiz ok (10 items)")

        evaluate = client.post(
            "/assessment/placement/evaluate",
            json={
                "user_id": USER_ID,
                "grade": GRADE,
                "completed_chapters_count": 3,
                "past_grade_marks_range": "50_75",
                "quiz_correct": 7,
                "quiz_total": 10,
            },
        )
        if evaluate.status_code != 200:
            _fail("POST /assessment/placement/evaluate", evaluate.text)
        category = evaluate.json().get("category")
        if category != "AVERAGE":
            _fail("POST /assessment/placement/evaluate", f"expected AVERAGE, got {category}")
        print(f"  evaluate ok category={category} score={evaluate.json().get('weighted_score')}")

        try:
            generated = client.post(
                "/teacher/generate",
                json={"topic_id": "G6_C7_MAG_POLES", "dok_level": 2, "question_type": "MCQ", "count": 1},
                timeout=60.0,
            )
            if generated.status_code == 200 and generated.json().get("created"):
                print("  teacher generate ok")
            else:
                print(
                    f"  teacher generate skipped ({generated.status_code}): "
                    f"{generated.text[:180]}"
                )
        except Exception as exc:
            print(f"  teacher generate skipped ({type(exc).__name__}: {exc})")

        pending_id = seeded["pending"].id
        approved = client.post(f"/teacher/questions/{pending_id}/approve")
        if approved.status_code != 200 or approved.json().get("status") != "approved":
            _fail("POST /teacher/questions/{id}/approve", approved.text)
        print("  teacher approve ok")

        session = client.post(
            "/assessment/sessions",
            json={"chapter_name": CHAPTER, "grade": GRADE, "user_id": USER_ID},
        )
        if session.status_code != 200:
            _fail("POST /assessment/sessions", session.text)
        session_id = session.json()["session_id"]

        nxt = client.post(f"/assessment/sessions/{session_id}/next")
        if nxt.status_code != 200:
            _fail("POST /assessment/sessions/{id}/next", nxt.text)
        print("  session + next ok")

        cases = [
            ("mcq", seeded["mcq"].id, "D", {"expect_distractor": True}),
            ("sa", seeded["sa"].id, "A magnet attracts iron", {"expect_error": False}),
            ("mb", seeded["mb"].id, "magnet|steel", {"expect_error": True}),
            ("tf", seeded["tf"].id, "True", {}),
        ]
        for label, question_id, answer, flags in cases:
            response = client.post(
                f"/assessment/sessions/{session_id}/answer",
                json={
                    "question_id": question_id,
                    "student_answer": answer,
                    "time_taken_seconds": 8.0,
                },
            )
            if response.status_code != 200:
                _fail(f"POST answer {label}", response.text)
            grade = response.json()["grade"]
            if label == "sa":
                if not grade.get("is_correct") or grade.get("error_category") != "NO_ERROR":
                    _fail("grade SA", str(grade))
            if label == "mb":
                if grade.get("error_category") != "PARTIAL_MASTERY" or not grade.get("missed_blanks"):
                    _fail("grade MultiBlank", str(grade))
            if label == "tf":
                if grade.get("is_correct") or not grade.get("concept_explanation"):
                    _fail("grade TrueFalse", str(grade))
            if label == "mcq":
                if grade.get("is_correct") or not grade.get("distractor_tag") or not grade.get("distractor_label"):
                    _fail("grade MCQ", str(grade))
            _assert_db_diagnostics(question_id, **flags)
            print(f"  grade {label} ok tag={grade.get('distractor_tag')} cat={grade.get('error_category')}")

        engine = get_engine()
        with engine.connect() as conn:
            attempts = conn.execute(
                text(
                    "SELECT count(*) FROM question_engine.attempts "
                    "WHERE user_id = :uid AND session_id = :sid"
                ),
                {"uid": USER_ID, "sid": session_id},
            ).scalar_one()
            served = conn.execute(
                text("SELECT count(*) FROM question_engine.served_questions WHERE user_id = :uid"),
                {"uid": USER_ID},
            ).scalar_one()
        if int(attempts) < 4:
            _fail("db.attempts", f"expected >=4 attempt rows, got {attempts}")
        if int(served) < 1:
            _fail("db.served_questions", "next_question did not insert served_questions")
        print(f"  postgres attempts={attempts} served={served}")

    print("\nAll e2e checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
