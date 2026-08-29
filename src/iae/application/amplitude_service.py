"""Aptitude Test use cases (initial diagnostic categorization)."""

from __future__ import annotations

from iae.application.amplitude_scoring import (
    categorize,
    history_composite_score,
    weighted_amplitude_score,
)
from iae.application.grading import GradingService
from iae.config.settings import get_config
from iae.domain.chapter_catalog import chapter_count_for_grade, get_chapter
from iae.domain.models import (
    AmplitudeEvaluation,
    PastGradeMarksRange,
    Question,
    StudentProfile,
)
from iae.infrastructure.postgres.amplitude_repo import PostgresAmplitudeRepository


class AmplitudeQuizUnavailable(RuntimeError):
    pass


class AmplitudeSurveyInvalid(ValueError):
    pass


def resolve_chapter_selection(
    *,
    grade: int,
    completed_chapter_ids: list[str] | None,
    completed_chapters_count: int | None,
) -> tuple[list[str], int]:
    """Validate chapter multi-select; empty list means student has not started the grade."""
    if completed_chapter_ids is not None:
        cleaned: list[str] = []
        for raw in completed_chapter_ids:
            cid = (raw or "").strip().upper().replace("-", "_")
            if not cid:
                continue
            record = get_chapter(cid)
            if record is None:
                raise AmplitudeSurveyInvalid(f"Unknown chapter_id: {raw}")
            if record.grade != grade:
                raise AmplitudeSurveyInvalid(
                    f"Chapter {cid} belongs to grade {record.grade}, not grade {grade}."
                )
            if cid not in cleaned:
                cleaned.append(cid)
        return cleaned, len(cleaned)
    if completed_chapters_count is None:
        # Neither provided → treat as zero chapters (new student).
        return [], 0
    count = int(completed_chapters_count)
    if count < 0:
        raise AmplitudeSurveyInvalid("completed_chapters_count must be >= 0")
    return [], count


class AmplitudeService:
    def __init__(
        self,
        *,
        store: PostgresAmplitudeRepository,
        grading: GradingService,
    ) -> None:
        self._store = store
        self._grading = grading

    def save_survey(
        self,
        *,
        user_id: str,
        grade: int,
        past_grade_marks_range: PastGradeMarksRange,
        completed_chapter_ids: list[str] | None = None,
        completed_chapters_count: int | None = None,
        study_hours_per_week: float | None = None,
        self_confidence: int | None = None,
        science_self_efficacy: int | None = 3,
        prerequisite_ready_count: int | None = 2,
    ) -> StudentProfile:
        chapter_ids, count = resolve_chapter_selection(
            grade=grade,
            completed_chapter_ids=completed_chapter_ids,
            completed_chapters_count=completed_chapters_count,
        )
        return self._store.upsert_survey(
            user_id=user_id,
            grade=grade,
            completed_chapters_count=count,
            completed_chapter_ids=chapter_ids,
            past_grade_marks_range=past_grade_marks_range,
            study_hours_per_week=study_hours_per_week,
            self_confidence=self_confidence,
            science_self_efficacy=science_self_efficacy,
            prerequisite_ready_count=prerequisite_ready_count,
        )

    def _load_fixed_quiz(self, grade: int) -> list[Question]:
        questions = self._store.list_amplitude_questions(grade)
        if len(questions) != 10:
            raise AmplitudeQuizUnavailable(
                f"Aptitude placement bank for grade {grade} needs exactly 10 approved "
                f"items; found {len(questions)}. Run: python -m scripts.generate_amplitude_bank "
                f"--grade {grade}"
            )
        return questions

    def diagnostic_quiz(self, grade: int) -> list[Question]:
        return self._load_fixed_quiz(grade)

    def evaluate(
        self,
        *,
        user_id: str,
        grade: int,
        past_grade_marks_range: PastGradeMarksRange,
        answers: dict[str, str],
        completed_chapter_ids: list[str] | None = None,
        completed_chapters_count: int | None = None,
        study_hours_per_week: float | None = None,
        self_confidence: int | None = None,
        science_self_efficacy: int | None = 3,
        prerequisite_ready_count: int | None = 2,
    ) -> AmplitudeEvaluation:
        chapter_ids, count = resolve_chapter_selection(
            grade=grade,
            completed_chapter_ids=completed_chapter_ids,
            completed_chapters_count=completed_chapters_count,
        )
        questions = self._load_fixed_quiz(grade)
        correct = 0
        for question in questions:
            student_answer = answers.get(question.id, "")
            result = self._grading.grade(question, student_answer)
            if result.is_correct:
                correct += 1
        total = len(questions)
        quiz_score = correct / total if total else 0.0
        config = get_config()
        expected = chapter_count_for_grade(grade) or 12
        history_score = history_composite_score(
            past_grade_marks_range=past_grade_marks_range,
            completed_chapters_count=count,
            study_hours_per_week=study_hours_per_week,
            self_confidence=self_confidence,
            science_self_efficacy=science_self_efficacy,
            prerequisite_ready_count=prerequisite_ready_count,
            expected_chapters=expected,
        )
        weighted = weighted_amplitude_score(
            quiz_score=quiz_score,
            history_score=history_score,
            quiz_weight=config.aptitude_quiz_weight,
            history_weight=config.aptitude_history_weight,
        )
        category = categorize(weighted)
        evaluation = AmplitudeEvaluation(
            user_id=user_id,
            grade=grade,
            completed_chapters_count=count,
            completed_chapter_ids=chapter_ids,
            past_grade_marks_range=past_grade_marks_range,
            study_hours_per_week=study_hours_per_week,
            self_confidence=self_confidence,
            science_self_efficacy=science_self_efficacy,
            prerequisite_ready_count=prerequisite_ready_count,
            question_ids=[q.id for q in questions],
            answers=dict(answers),
            quiz_correct=correct,
            quiz_total=total,
            quiz_score=quiz_score,
            history_score=history_score,
            weighted_score=weighted,
            category=category,
        )
        return self._store.save_evaluation(evaluation)

    def initial_category(self, student_id: str) -> StudentProfile | None:
        return self._store.get_user(student_id)
