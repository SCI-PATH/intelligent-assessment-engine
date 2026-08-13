"""PostgreSQL adapter for student placement profiles and evaluations."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from iae.core.models import (
    PastGradeMarksRange,
    PlacementCategory,
    PlacementEvaluation,
    StudentProfile,
)
from iae.infrastructure.postgres.orm import PlacementEvaluationRow, UserRow


def _profile_from_row(row: UserRow) -> StudentProfile:
    marks = None
    if row.past_grade_marks_range:
        marks = PastGradeMarksRange(row.past_grade_marks_range)
    category = None
    if row.placement_category:
        category = PlacementCategory(row.placement_category)
    return StudentProfile(
        user_id=row.user_id,
        grade=row.grade,
        completed_chapters_count=row.completed_chapters_count,
        past_grade_marks_range=marks,
        placement_category=category,
        placement_score=row.placement_score,
        created_at=row.created_at,
        updated_at=row.updated_at or row.created_at,
    )


class PostgresPlacementRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert_survey(
        self,
        *,
        user_id: str,
        grade: int,
        completed_chapters_count: int,
        past_grade_marks_range: PastGradeMarksRange,
    ) -> StudentProfile:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                row = UserRow(user_id=user_id, created_at=now)
                session.add(row)
            row.grade = grade
            row.completed_chapters_count = completed_chapters_count
            row.past_grade_marks_range = past_grade_marks_range.value
            row.updated_at = now
            session.commit()
            session.refresh(row)
            return _profile_from_row(row)

    def save_evaluation(self, evaluation: PlacementEvaluation) -> PlacementEvaluation:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            user = session.get(UserRow, evaluation.user_id)
            if user is None:
                user = UserRow(user_id=evaluation.user_id, created_at=now)
                session.add(user)
            user.grade = evaluation.grade
            user.completed_chapters_count = evaluation.completed_chapters_count
            user.past_grade_marks_range = evaluation.past_grade_marks_range.value
            user.placement_category = evaluation.category.value
            user.placement_score = evaluation.weighted_score
            user.updated_at = now
            session.add(
                PlacementEvaluationRow(
                    id=UUID(evaluation.id),
                    user_id=evaluation.user_id,
                    grade=evaluation.grade,
                    completed_chapters_count=evaluation.completed_chapters_count,
                    past_grade_marks_range=evaluation.past_grade_marks_range.value,
                    quiz_correct=evaluation.quiz_correct,
                    quiz_total=evaluation.quiz_total,
                    quiz_score=evaluation.quiz_score,
                    past_score=evaluation.past_score,
                    weighted_score=evaluation.weighted_score,
                    category=evaluation.category.value,
                    created_at=evaluation.created_at,
                )
            )
            session.commit()
        return evaluation
