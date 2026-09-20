"""Persist analytics payloads in ``question_engine.analytics_events``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session, sessionmaker

from iae.infrastructure.postgres.orm import AnalyticsEventRow, AttemptRow


class PostgresAnalyticsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def insert(
        self,
        payload: dict[str, Any],
        *,
        session_id: str | None = None,
    ) -> str:
        event_id = uuid4()
        row = AnalyticsEventRow(
            id=event_id,
            user_id=str(payload.get("user_id") or ""),
            topic_id=str(payload.get("topic_id") or ""),
            is_correct=bool(payload.get("is_correct")),
            question_id=str(payload.get("question_id") or ""),
            question_type=str(payload.get("question_type") or ""),
            similarity_score=payload.get("similarity_score"),
            distractor_tag=payload.get("distractor_tag"),
            distractor_label=payload.get("distractor_label"),
            error_category=payload.get("error_category"),
            missing_keywords=payload.get("missing_keywords"),
            detailed_explanation=payload.get("detailed_explanation"),
            missed_blanks=payload.get("missed_blanks"),
            concept_explanation=payload.get("concept_explanation"),
            session_id=session_id,
            response_time_s=payload.get("response_time_s"),
            difficulty_level=payload.get("difficulty_level"),
            subtopic_id=payload.get("subtopic_id"),
            chosen_distractor_text=payload.get("chosen_distractor_text"),
            source=payload.get("source"),
            payload=dict(payload),
            created_at=datetime.now(timezone.utc),
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()
        return str(event_id)

    def most_missed(
        self,
        *,
        user_ids: list[str] | None = None,
        limit: int = 8,
    ) -> list[tuple[str, int, int]]:
        """Return (question_id, attempt_count, incorrect_count) ordered by misses."""
        incorrect = func.sum(
            case((AnalyticsEventRow.is_correct.is_(False), 1), else_=0)
        )
        attempts = func.count()
        cap = max(1, min(int(limit), 100))
        stmt = (
            select(
                AnalyticsEventRow.question_id,
                attempts.label("attempt_count"),
                incorrect.label("incorrect_count"),
            )
            .where(AnalyticsEventRow.question_id != "")
            .group_by(AnalyticsEventRow.question_id)
            .having(incorrect > 0)
            .order_by(desc(incorrect), desc(attempts))
            .limit(cap)
        )
        if user_ids:
            stmt = stmt.where(AnalyticsEventRow.user_id.in_(user_ids))
        with self._session_factory() as session:
            rows = session.execute(stmt).all()
            return [
                (
                    str(row.question_id),
                    int(row.attempt_count),
                    int(row.incorrect_count),
                )
                for row in rows
            ]

    def answer_counts(
        self, question_id: str
    ) -> list[tuple[str, int, int]]:
        """Return (student_answer, total_count, incorrect_count) for one item."""
        if not question_id:
            return []
        total = func.count()
        incorrect = func.sum(
            case((AttemptRow.is_correct.is_(False), 1), else_=0)
        )
        stmt = (
            select(
                AttemptRow.student_answer,
                total.label("total_count"),
                incorrect.label("incorrect_count"),
            )
            .where(AttemptRow.question_id == question_id)
            .where(AttemptRow.student_answer != "")
            .group_by(AttemptRow.student_answer)
            .order_by(desc(total))
        )
        with self._session_factory() as session:
            rows = session.execute(stmt).all()
            return [
                (
                    str(row.student_answer).strip(),
                    int(row.total_count),
                    int(row.incorrect_count or 0),
                )
                for row in rows
                if str(row.student_answer).strip()
            ]
