"""Aptitude attempts + placement-question catalog persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from iae.domain.models import (
    AmplitudeCategory,
    AmplitudeEvaluation,
    PastGradeMarksRange,
    Question,
    QuestionOrigin,
    QuestionStatus,
    QuestionType,
    StudentProfile,
    UserRole,
)
from iae.infrastructure.postgres.orm import (
    AmplitudeAttemptRow,
    AmplitudeFixedItemRow,
    AmplitudeQuestionRow,
    UserRow,
)


def _parse_category(raw: str | None) -> AmplitudeCategory | None:
    if not raw:
        return None
    try:
        return AmplitudeCategory(raw)
    except ValueError:
        if raw == "WEAK":
            return AmplitudeCategory.BASIC
        if raw == "AVERAGE":
            return AmplitudeCategory.INTERMEDIATE
        if raw == "ADVANCED":
            return AmplitudeCategory.ADVANCED
        return None


def profile_from_user(row: UserRow) -> StudentProfile:
    marks = PastGradeMarksRange(row.past_grade_marks_range) if row.past_grade_marks_range else None
    role = UserRole(row.role) if row.role in {r.value for r in UserRole} else UserRole.STUDENT
    chapter_ids = list(row.completed_chapter_ids or [])
    return StudentProfile(
        user_id=row.user_id,
        grade=row.grade,
        completed_chapters_count=row.completed_chapters_count,
        completed_chapter_ids=chapter_ids,
        past_grade_marks_range=marks,
        placement_category=_parse_category(row.placement_category),
        placement_score=row.placement_score,
        role=role,
        class_code=row.class_code,
        display_name=row.display_name,
        study_hours_per_week=row.study_hours_per_week,
        self_confidence=row.self_confidence,
        science_self_efficacy=row.science_self_efficacy,
        prerequisite_ready_count=row.prerequisite_ready_count,
        initial_category=_parse_category(row.initial_category),
        initial_category_score=row.initial_category_score,
        created_at=row.created_at,
        updated_at=row.updated_at or row.created_at,
    )


def _amplitude_row_to_question(row: AmplitudeQuestionRow) -> Question:
    return Question(
        id=str(row.id),
        chapter_name=row.chapter_name,
        sub_concept=row.sub_concept or "",
        dok_level=int(row.baseline_level),
        question_type=QuestionType(row.question_type),
        payload=row.payload,
        chunk_ids=list(row.chunk_ids or []),
        grade=row.grade,
        topic_id=row.topic_id or "",
        skill=row.skill or "",
        status=QuestionStatus.APPROVED,
        origin=QuestionOrigin.AMPLITUDE,
        created_at=row.created_at,
    )


class PostgresAmplitudeRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert_survey(
        self,
        *,
        user_id: str,
        grade: int,
        completed_chapters_count: int,
        completed_chapter_ids: list[str],
        past_grade_marks_range: PastGradeMarksRange,
        study_hours_per_week: float | None,
        self_confidence: int | None,
        science_self_efficacy: int | None,
        prerequisite_ready_count: int | None,
    ) -> StudentProfile:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                row = UserRow(user_id=user_id, created_at=now, role=UserRole.STUDENT.value)
                session.add(row)
            row.grade = grade
            row.completed_chapters_count = completed_chapters_count
            row.completed_chapter_ids = list(completed_chapter_ids)
            row.past_grade_marks_range = past_grade_marks_range.value
            row.study_hours_per_week = study_hours_per_week
            row.self_confidence = self_confidence
            row.science_self_efficacy = science_self_efficacy
            row.prerequisite_ready_count = prerequisite_ready_count
            row.updated_at = now
            session.commit()
            session.refresh(row)
            return profile_from_user(row)

    def get_user(self, user_id: str) -> StudentProfile | None:
        with self._session_factory() as session:
            row = session.get(UserRow, user_id)
            return profile_from_user(row) if row else None

    def save_evaluation(self, evaluation: AmplitudeEvaluation) -> AmplitudeEvaluation:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            user = session.get(UserRow, evaluation.user_id)
            if user is None:
                user = UserRow(user_id=evaluation.user_id, created_at=now, role=UserRole.STUDENT.value)
                session.add(user)
            user.grade = evaluation.grade
            user.completed_chapters_count = evaluation.completed_chapters_count
            user.completed_chapter_ids = list(evaluation.completed_chapter_ids)
            user.past_grade_marks_range = evaluation.past_grade_marks_range.value
            user.study_hours_per_week = evaluation.study_hours_per_week
            user.self_confidence = evaluation.self_confidence
            user.science_self_efficacy = evaluation.science_self_efficacy
            user.prerequisite_ready_count = evaluation.prerequisite_ready_count
            user.initial_category = evaluation.category.value
            user.initial_category_score = evaluation.weighted_score
            user.placement_category = evaluation.category.value
            user.placement_score = evaluation.weighted_score
            user.updated_at = now
            session.flush()
            session.add(
                AmplitudeAttemptRow(
                    id=UUID(evaluation.id),
                    user_id=evaluation.user_id,
                    grade=evaluation.grade,
                    completed_chapters_count=evaluation.completed_chapters_count,
                    completed_chapter_ids=list(evaluation.completed_chapter_ids),
                    past_grade_marks_range=evaluation.past_grade_marks_range.value,
                    study_hours_per_week=evaluation.study_hours_per_week,
                    self_confidence=evaluation.self_confidence,
                    science_self_efficacy=evaluation.science_self_efficacy,
                    prerequisite_ready_count=evaluation.prerequisite_ready_count,
                    question_ids=list(evaluation.question_ids),
                    answers=dict(evaluation.answers),
                    quiz_correct=evaluation.quiz_correct,
                    quiz_total=evaluation.quiz_total,
                    quiz_score=evaluation.quiz_score,
                    history_score=evaluation.history_score,
                    weighted_score=evaluation.weighted_score,
                    category=evaluation.category.value,
                    created_at=evaluation.created_at or now,
                )
            )
            session.commit()
        return evaluation

    def count_amplitude_questions(self, grade: int) -> int:
        with self._session_factory() as session:
            rows = session.execute(
                select(AmplitudeQuestionRow.id).where(AmplitudeQuestionRow.grade == grade)
            ).all()
            return len(rows)

    def list_amplitude_questions(self, grade: int) -> list[Question]:
        with self._session_factory() as session:
            rows = (
                session.execute(
                    select(AmplitudeQuestionRow)
                    .where(AmplitudeQuestionRow.grade == grade)
                    .order_by(AmplitudeQuestionRow.position)
                )
                .scalars()
                .all()
            )
            return [_amplitude_row_to_question(row) for row in rows]

    def replace_amplitude_questions(self, grade: int, items: list[tuple[int, int, Question]]) -> None:
        """Replace all Aptitude items for a grade.

        ``items`` is a list of ``(position, baseline_level, question)``.
        """
        with self._session_factory() as session:
            session.execute(delete(AmplitudeQuestionRow).where(AmplitudeQuestionRow.grade == grade))
            session.execute(delete(AmplitudeFixedItemRow).where(AmplitudeFixedItemRow.grade == grade))
            for position, baseline_level, question in items:
                session.add(
                    AmplitudeQuestionRow(
                        id=UUID(question.id),
                        grade=grade,
                        position=position,
                        topic_id=question.topic_id or "",
                        chapter_name=question.chapter_name,
                        sub_concept=question.sub_concept or "",
                        skill=question.skill or "",
                        baseline_level=baseline_level,
                        question_type=question.question_type.value,
                        payload=question.payload.model_dump(mode="json"),
                        chunk_ids=list(question.chunk_ids or []),
                        status=QuestionStatus.APPROVED.value,
                        origin=QuestionOrigin.AMPLITUDE.value,
                        created_at=question.created_at,
                    )
                )
                session.add(
                    AmplitudeFixedItemRow(
                        grade=grade,
                        position=position,
                        question_id=question.id,
                    )
                )
            session.commit()

    def get_fixed_question_ids(self, grade: int) -> list[str]:
        with self._session_factory() as session:
            rows = (
                session.execute(
                    select(AmplitudeFixedItemRow)
                    .where(AmplitudeFixedItemRow.grade == grade)
                    .order_by(AmplitudeFixedItemRow.position)
                )
                .scalars()
                .all()
            )
            return [row.question_id for row in rows]

    def replace_fixed_question_ids(self, grade: int, question_ids: list[str]) -> None:
        with self._session_factory() as session:
            session.execute(delete(AmplitudeFixedItemRow).where(AmplitudeFixedItemRow.grade == grade))
            for index, qid in enumerate(question_ids[:10], start=1):
                session.add(AmplitudeFixedItemRow(grade=grade, position=index, question_id=qid))
            session.commit()

    def upsert_user(
        self,
        *,
        user_id: str,
        role: UserRole,
        display_name: str,
        class_code: str | None = None,
        grade: int | None = None,
    ) -> StudentProfile:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                row = UserRow(user_id=user_id, created_at=now)
                session.add(row)
            row.role = role.value
            row.display_name = display_name
            row.class_code = class_code
            if grade is not None:
                row.grade = grade
            row.updated_at = now
            session.commit()
            session.refresh(row)
            return profile_from_user(row)

    def list_users_by_class(self, class_code: str) -> list[StudentProfile]:
        with self._session_factory() as session:
            rows = session.execute(
                select(UserRow).where(UserRow.class_code == class_code)
            ).scalars().all()
            return [profile_from_user(row) for row in rows]
