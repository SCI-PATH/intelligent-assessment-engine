"""Persist analytics payloads in ``question_engine.analytics_events``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from iae.infrastructure.postgres.orm import AnalyticsEventRow


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
            payload=dict(payload),
            created_at=datetime.now(timezone.utc),
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()
        return str(event_id)
