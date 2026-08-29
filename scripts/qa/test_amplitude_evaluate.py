"""Evaluate-path tests: seed 10 Aptitude items in-memory via repo replace + score paths.

Requires DATABASE_URL / Neon. Seeds a temporary grade-6 set if missing, then
exercises survey (zero chapters) + evaluate category logic with a FakeGrader.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from iae.application.amplitude_service import AmplitudeService
from iae.domain.models import (
    GradeResult,
    MCQPayload,
    PastGradeMarksRange,
    Question,
    QuestionOrigin,
    QuestionStatus,
    QuestionType,
    TrueFalsePayload,
)
from iae.infrastructure.postgres.amplitude_repo import PostgresAmplitudeRepository
from iae.infrastructure.postgres.engine import get_session_factory, init_schema

GRADE = 6


class FakeGrader:
    """Mark correct when student_answer equals the stored correct_answer."""

    def grade(self, question: Question, student_answer: str) -> GradeResult:
        payload = question.payload
        correct = str(getattr(payload, "correct_answer", "")).strip()
        ok = student_answer.strip() == correct or student_answer.strip().upper() == correct.upper()
        return GradeResult(accuracy_score=1.0 if ok else 0.0, is_correct=ok, feedback="")


def _seed_ten(repo: PostgresAmplitudeRepository) -> list[Question]:
    items: list[tuple[int, int, Question]] = []
    for position in range(1, 11):
        abl = 1 if position <= 4 else (2 if position <= 8 else 3)
        if position in (4, 8, 10):
            q = Question(
                id=str(uuid4()),
                chapter_name="Wonders of the Living World",
                sub_concept="AptitudeSeed",
                dok_level=abl,
                question_type=QuestionType.TRUE_FALSE,
                payload=TrueFalsePayload(
                    question=f"Seed TF statement {position}.",
                    correct_answer="True",
                    distractor_tag="MISCONCEPTION",
                    distractor_label="Flips a basic living-world fact",
                ),
                grade=GRADE,
                topic_id="G6_C1_ORG_CHARS",
                skill="seed",
                status=QuestionStatus.APPROVED,
                origin=QuestionOrigin.AMPLITUDE,
            )
        else:
            q = Question(
                id=str(uuid4()),
                chapter_name="Wonders of the Living World",
                sub_concept="AptitudeSeed",
                dok_level=abl,
                question_type=QuestionType.MCQ,
                payload=MCQPayload(
                    question=f"Seed MCQ {position}?",
                    options={"A": "Right", "B": "Wrong1", "C": "Wrong2", "D": "Wrong3"},
                    correct_answer="A",
                    option_diagnostics={
                        "B": {
                            "distractor_tag": "NEAR_MISS",
                            "distractor_label": "Near miss seed",
                        },
                        "C": {
                            "distractor_tag": "MISCONCEPTION",
                            "distractor_label": "Misconception seed",
                        },
                        "D": {
                            "distractor_tag": "COMPLETE_MISS",
                            "distractor_label": "Complete miss seed",
                        },
                    },
                ),
                grade=GRADE,
                topic_id="G6_C1_ORG_CHARS",
                skill="seed",
                status=QuestionStatus.APPROVED,
                origin=QuestionOrigin.AMPLITUDE,
            )
        items.append((position, abl, q))
    repo.replace_amplitude_questions(GRADE, items)
    return [q for _, _, q in items]


def main() -> int:
    init_schema()
    repo = PostgresAmplitudeRepository(get_session_factory())
    existing = repo.list_amplitude_questions(GRADE)
    if len(existing) != 10:
        print(f"Seeding 10 Aptitude items for grade {GRADE} (test fixture)…")
        questions = _seed_ten(repo)
    else:
        questions = existing
        print(f"Using existing {len(questions)} Aptitude items for grade {GRADE}")

    service = AmplitudeService(store=repo, grading=FakeGrader())  # type: ignore[arg-type]
    user = f"amp-test-{uuid4().hex[:8]}"

    # Zero chapters + weak marks + all wrong → BASIC
    wrong = {q.id: "B" if q.question_type == QuestionType.MCQ else "False" for q in questions}
    basic = service.evaluate(
        user_id=user,
        grade=GRADE,
        past_grade_marks_range=PastGradeMarksRange.BELOW_50,
        completed_chapter_ids=[],
        study_hours_per_week=0,
        self_confidence=1,
        science_self_efficacy=1,
        prerequisite_ready_count=0,
        answers=wrong,
    )
    assert basic.category.value == "BASIC", basic
    print("evaluate BASIC ok", basic.weighted_score)

    # Perfect quiz + strong history → ADVANCED
    right = {}
    for q in questions:
        if q.question_type == QuestionType.MCQ:
            right[q.id] = q.payload.correct_answer
        else:
            right[q.id] = q.payload.correct_answer
    advanced = service.evaluate(
        user_id=user + "-adv",
        grade=GRADE,
        past_grade_marks_range=PastGradeMarksRange.ABOVE_75,
        completed_chapter_ids=["G6_C1", "G6_C2", "G6_C3", "G6_C4", "G6_C5"],
        study_hours_per_week=12,
        self_confidence=5,
        science_self_efficacy=5,
        prerequisite_ready_count=5,
        answers=right,
    )
    assert advanced.category.value == "ADVANCED", advanced
    print("evaluate ADVANCED ok", advanced.weighted_score)

    # Mid quiz (5/10) + mid history → INTERMEDIATE
    mid_answers = dict(wrong)
    for q in questions[:5]:
        mid_answers[q.id] = q.payload.correct_answer
    mid = service.evaluate(
        user_id=user + "-mid",
        grade=GRADE,
        past_grade_marks_range=PastGradeMarksRange.BAND_50_75,
        completed_chapter_ids=["G6_C1", "G6_C2"],
        study_hours_per_week=5,
        self_confidence=3,
        science_self_efficacy=3,
        prerequisite_ready_count=2,
        answers=mid_answers,
    )
    assert mid.category.value == "INTERMEDIATE", mid
    print("evaluate INTERMEDIATE ok", mid.weighted_score)

    # Survey with empty chapters must succeed
    profile = service.save_survey(
        user_id=user + "-survey",
        grade=GRADE,
        past_grade_marks_range=PastGradeMarksRange.BAND_50_75,
        completed_chapter_ids=[],
        science_self_efficacy=4,
        prerequisite_ready_count=3,
    )
    assert profile.completed_chapters_count == 0
    assert profile.completed_chapter_ids == []
    print("survey zero-chapters ok")

    print("APTITUDE_EVALUATE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
