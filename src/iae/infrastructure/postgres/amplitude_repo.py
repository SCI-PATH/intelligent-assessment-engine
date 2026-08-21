"""Amplitude attempts + fixed-item catalog persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from iae.domain.models import (
    AmplitudeCategory,
    AmplitudeEvaluation,
    PastGradeMarksRange,
    StudentProfile,
    UserRole,
)
from iae.infrastructure.postgres.orm import AmplitudeAttemptRow, AmplitudeFixedItemRow, UserRow


def _parse_category(raw: str | None) -> AmplitudeCategory | None:
    if not raw:
        return None
    try:
        return AmplitudeCategory(raw)
    except ValueError:
        # Map legacy placement labels.
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
    return StudentProfile(
        user_id=row.user_id,
        grade=row.grade,
        completed_chapters_count=row.completed_chapters_count,
        past_grade_marks_range=marks,
        placement_category=_parse_category(row.placement_category),
        placement_score=row.placement_score,
        role=role,
        class_code=row.class_code,
        display_name=row.display_name,
        study_hours_per_week=row.study_hours_per_week,
        self_confidence=row.self_confidence,
        initial_category=_parse_category(row.initial_category),
        initial_category_score=row.initial_category_score,
        created_at=row.created_at,
        updated_at=row.updated_at or row.created_at,
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
        past_grade_marks_range: PastGradeMarksRange,
        study_hours_per_week: float | None,
        self_confidence: int | None,
    ) -> StudentProfile:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                row = UserRow(user_id=user_id, created_at=now, role=UserRole.STUDENT.value)
                session.add(row)
            row.grade = grade
            row.completed_chapters_count = completed_chapters_count
            row.past_grade_marks_range = past_grade_marks_range.value
            row.study_hours_per_week = study_hours_per_week
            row.self_confidence = self_confidence
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
            user.past_grade_marks_range = evaluation.past_grade_marks_range.value
            user.study_hours_per_week = evaluation.study_hours_per_week
            user.self_confidence = evaluation.self_confidence
            user.initial_category = evaluation.category.value
            user.initial_category_score = evaluation.weighted_score
            user.placement_category = evaluation.category.value
            user.placement_score = evaluation.weighted_score
            user.updated_at = now
            session.add(
                AmplitudeAttemptRow(
                    id=UUID(evaluation.id),
                    user_id=evaluation.user_id,
                    grade=evaluation.grade,
                    completed_chapters_count=evaluation.completed_chapters_count,
                    past_grade_marks_range=evaluation.past_grade_marks_range.value,
                    study_hours_per_week=evaluation.study_hours_per_week,
                    self_confidence=evaluation.self_confidence,
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

    def get_fixed_question_ids(self, grade: int) -> list[str]:
        with self._session_factory() as session:
            rows = session.execute(
                select(AmplitudeFixedItemRow)
                .where(AmplitudeFixedItemRow.grade == grade)
                .order_by(AmplitudeFixedItemRow.position)
            ).scalars().all()
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
