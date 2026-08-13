"""Student initial placement: survey, standardized quiz, weighted category."""

from __future__ import annotations

from collections import defaultdict

from iae.core.models import (
    PastGradeMarksRange,
    PlacementCategory,
    PlacementEvaluation,
    Question,
    QuestionStatus,
    StudentProfile,
)
from iae.core.protocols import IPlacementRepository, IQuestionRepository

QUIZ_SIZE = 10
QUIZ_WEIGHT = 0.70
PAST_WEIGHT = 0.30

_PAST_SCORE = {
    PastGradeMarksRange.BELOW_50: 0.25,
    PastGradeMarksRange.BAND_50_75: 0.625,
    PastGradeMarksRange.ABOVE_75: 0.875,
}


class PlacementQuizUnavailable(RuntimeError):
    """Raised when the approved bank cannot supply 10 foundational items."""


def past_performance_score(marks: PastGradeMarksRange) -> float:
    return _PAST_SCORE[marks]


def categorize(weighted_score: float) -> PlacementCategory:
    if weighted_score < 0.50:
        return PlacementCategory.WEAK
    if weighted_score <= 0.75:
        return PlacementCategory.AVERAGE
    return PlacementCategory.ADVANCED


def weighted_placement_score(*, quiz_score: float, past_score: float) -> float:
    return round((QUIZ_WEIGHT * quiz_score) + (PAST_WEIGHT * past_score), 4)


def select_foundational_quiz(questions: list[Question], *, size: int = QUIZ_SIZE) -> list[Question]:
    """Spread items across topic_id (then chapter) so the 10 cover core topics."""
    by_topic: dict[str, list[Question]] = defaultdict(list)
    for question in questions:
        key = question.topic_id or question.chapter_name or question.id
        by_topic[key].append(question)

    buckets = list(by_topic.values())
    selected: list[Question] = []
    seen: set[str] = set()
    index = 0
    while len(selected) < size and buckets:
        progressed = False
        for bucket in buckets:
            if index < len(bucket):
                candidate = bucket[index]
                if candidate.id not in seen:
                    selected.append(candidate)
                    seen.add(candidate.id)
                    progressed = True
                if len(selected) >= size:
                    break
        if not progressed:
            break
        index += 1
    return selected[:size]


class PlacementService:
    def __init__(self, *, store: IPlacementRepository, questions: IQuestionRepository) -> None:
        self._store = store
        self._questions = questions

    def save_survey(
        self,
        *,
        user_id: str,
        grade: int,
        completed_chapters_count: int,
        past_grade_marks_range: PastGradeMarksRange,
    ) -> StudentProfile:
        return self._store.upsert_survey(
            user_id=user_id,
            grade=grade,
            completed_chapters_count=completed_chapters_count,
            past_grade_marks_range=past_grade_marks_range,
        )

    def diagnostic_quiz(self, grade: int) -> list[Question]:
        pool = self._questions.list_questions(
            status=QuestionStatus.APPROVED,
            grade=grade,
            limit=400,
        )
        selected = select_foundational_quiz(pool, size=QUIZ_SIZE)
        if len(selected) < QUIZ_SIZE:
            raise PlacementQuizUnavailable(
                f"Need {QUIZ_SIZE} approved questions for grade {grade}; found {len(selected)}."
            )
        return selected

    def evaluate(
        self,
        *,
        user_id: str,
        grade: int,
        completed_chapters_count: int,
        past_grade_marks_range: PastGradeMarksRange,
        quiz_correct: int,
        quiz_total: int = QUIZ_SIZE,
    ) -> PlacementEvaluation:
        total = max(1, quiz_total)
        correct = max(0, min(quiz_correct, total))
        quiz_score = correct / total
        past_score = past_performance_score(past_grade_marks_range)
        weighted = weighted_placement_score(quiz_score=quiz_score, past_score=past_score)
        category = categorize(weighted)

        # TEAM INTEGRATION PLACEHOLDER: On Saturday, export this student category
        # to shared.learners and Dhiyanah's learner_analytics schema.
        evaluation = PlacementEvaluation(
            user_id=user_id,
            grade=grade,
            completed_chapters_count=completed_chapters_count,
            past_grade_marks_range=past_grade_marks_range,
            quiz_correct=correct,
            quiz_total=total,
            quiz_score=quiz_score,
            past_score=past_score,
            weighted_score=weighted,
            category=category,
        )
        return self._store.save_evaluation(evaluation)
