"""Amplitude Test use cases (initial diagnostic categorization)."""

from __future__ import annotations

from iae.amplitude import categorize, history_composite_score, weighted_amplitude_score
from iae.application.grading import GradingService
from iae.core.models import (
    AmplitudeEvaluation,
    PastGradeMarksRange,
    Question,
    QuestionStatus,
    StudentProfile,
)
from iae.core.settings import get_config
from iae.infrastructure.postgres.amplitude_repo import PostgresAmplitudeRepository
from iae.infrastructure.postgres.questions_repo import PostgresQuestionRepository


class AmplitudeQuizUnavailable(RuntimeError):
    pass


class AmplitudeService:
    def __init__(
        self,
        *,
        store: PostgresAmplitudeRepository,
        questions: PostgresQuestionRepository,
        grading: GradingService,
    ) -> None:
        self._store = store
        self._questions = questions
        self._grading = grading

    def save_survey(
        self,
        *,
        user_id: str,
        grade: int,
        completed_chapters_count: int,
        past_grade_marks_range: PastGradeMarksRange,
        study_hours_per_week: float | None,
        self_confidence: int | None,
    ) -> StudentProfile:
        return self._store.upsert_survey(
            user_id=user_id,
            grade=grade,
            completed_chapters_count=completed_chapters_count,
            past_grade_marks_range=past_grade_marks_range,
            study_hours_per_week=study_hours_per_week,
            self_confidence=self_confidence,
        )

    def _ensure_fixed_items(self, grade: int) -> list[Question]:
        ids = self._store.get_fixed_question_ids(grade)
        questions: list[Question] = []
        if ids:
            for qid in ids:
                item = self._questions.get(qid)
                if item is not None and item.status == QuestionStatus.APPROVED:
                    questions.append(item)
            if len(questions) == 10:
                return questions

        pool = self._questions.list_questions(status=QuestionStatus.APPROVED, grade=grade, limit=400)
        pool.sort(key=lambda q: (q.topic_id or "", q.id))
        by_topic: dict[str, list[Question]] = {}
        for q in pool:
            by_topic.setdefault(q.topic_id or q.chapter_name or q.id, []).append(q)
        selected: list[Question] = []
        buckets = list(by_topic.values())
        index = 0
        while len(selected) < 10 and buckets:
            progressed = False
            for bucket in buckets:
                if index < len(bucket):
                    selected.append(bucket[index])
                    progressed = True
                    if len(selected) >= 10:
                        break
            if not progressed:
                break
            index += 1
        if len(selected) < 10:
            raise AmplitudeQuizUnavailable(
                f"Need 10 approved questions for grade {grade}; found {len(selected)}."
            )
        self._store.replace_fixed_question_ids(grade, [q.id for q in selected])
        return selected

    def diagnostic_quiz(self, grade: int) -> list[Question]:
        return self._ensure_fixed_items(grade)

    def evaluate(
        self,
        *,
        user_id: str,
        grade: int,
        completed_chapters_count: int,
        past_grade_marks_range: PastGradeMarksRange,
        study_hours_per_week: float | None,
        self_confidence: int | None,
        answers: dict[str, str],
    ) -> AmplitudeEvaluation:
        questions = self._ensure_fixed_items(grade)
        correct = 0
        for question in questions:
            student_answer = answers.get(question.id, "")
            result = self._grading.grade(question, student_answer)
            if result.is_correct:
                correct += 1
        total = len(questions)
        quiz_score = correct / total if total else 0.0
        config = get_config()
        history_score = history_composite_score(
            past_grade_marks_range=past_grade_marks_range,
            completed_chapters_count=completed_chapters_count,
            study_hours_per_week=study_hours_per_week,
            self_confidence=self_confidence,
        )
        weighted = weighted_amplitude_score(
            quiz_score=quiz_score,
            history_score=history_score,
            quiz_weight=config.amplitude_quiz_weight,
            history_weight=config.amplitude_history_weight,
        )
        category = categorize(weighted)
        evaluation = AmplitudeEvaluation(
            user_id=user_id,
            grade=grade,
            completed_chapters_count=completed_chapters_count,
            past_grade_marks_range=past_grade_marks_range,
            study_hours_per_week=study_hours_per_week,
            self_confidence=self_confidence,
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
