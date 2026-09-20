"""PostgreSQL adapter for diagnostic sessions, served items, and attempts."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from iae.domain.models import (
    AttemptRecord,
    QuestionType,
    RlAction,
    RlState,
    SessionKind,
    SessionState,
    SessionStatus,
)
from iae.infrastructure.postgres.orm import (
    AssessmentSessionRow,
    AttemptRow,
    ServedQuestionRow,
    UserRow,
)


def _as_uuid(value: str) -> UUID:
    return UUID(str(value))


def _history_from_json(raw: list | None) -> list[AttemptRecord]:
    return [AttemptRecord(**item) for item in (raw or [])]


def _to_domain(row: AssessmentSessionRow) -> SessionState:
    kinds = {item.value: item for item in SessionKind}
    statuses = {item.value: item for item in SessionStatus}
    allowed: list[QuestionType] = []
    for raw in row.allowed_question_types or []:
        try:
            allowed.append(QuestionType(raw))
        except ValueError:
            continue
    return SessionState(
        session_id=str(row.session_id),
        user_id=row.user_id,
        scope_chapter=row.scope_chapter,
        used_question_ids=list(row.used_question_ids or []),
        asked_signatures=list(row.asked_signatures or []),
        history=_history_from_json(row.history),
        last_state=RlState(**row.last_state) if row.last_state else None,
        last_action=RlAction(**row.last_action) if row.last_action else None,
        questions_asked=row.questions_asked,
        grade=row.grade or 6,
        max_questions=row.max_questions,
        session_kind=kinds.get(row.session_kind or "diagnostic", SessionKind.DIAGNOSTIC),
        status=statuses.get(row.status or "active", SessionStatus.ACTIVE),
        terminate_reason=row.terminate_reason,
        allowed_question_types=allowed,
        scope_chapters=list(row.scope_chapters or []),
        elo_rating=float(row.elo_rating if row.elo_rating is not None else 1000.0),
        bkt_snapshot=row.bkt_snapshot,
        ai_analysis=row.ai_analysis,
        created_at=row.started_at,
        updated_at=row.updated_at,
    )


class PostgresSessionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ensure_user(self, user_id: str) -> None:
        with self._session_factory() as session:
            if session.get(UserRow, user_id) is None:
                session.add(UserRow(user_id=user_id))
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()

    def create(self, state: SessionState) -> SessionState:
        self.ensure_user(state.user_id)
        now = datetime.now(timezone.utc)
        row = AssessmentSessionRow(
            session_id=_as_uuid(state.session_id),
            user_id=state.user_id,
            grade=state.grade,
            topic_id=None,
            scope_chapter=state.scope_chapter,
            used_question_ids=list(state.used_question_ids),
            asked_signatures=list(state.asked_signatures),
            history=[item.model_dump(mode="json") for item in state.history],
            last_state=state.last_state.model_dump(mode="json") if state.last_state else None,
            last_action=state.last_action.model_dump(mode="json") if state.last_action else None,
            questions_asked=state.questions_asked,
            max_questions=state.max_questions,
            session_kind=state.session_kind.value,
            status=state.status.value,
            terminate_reason=state.terminate_reason,
            allowed_question_types=[t.value for t in state.allowed_question_types],
            scope_chapters=list(state.scope_chapters),
            elo_rating=state.elo_rating,
            bkt_snapshot=state.bkt_snapshot,
            ai_analysis=state.ai_analysis,
            started_at=state.created_at or now,
            updated_at=now,
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()
        return state

    def get(self, session_id: str) -> SessionState | None:
        try:
            pk = _as_uuid(session_id)
        except ValueError:
            return None
        with self._session_factory() as session:
            row = session.get(AssessmentSessionRow, pk)
            if row is None:
                return None
            return _to_domain(row)

    def update(self, state: SessionState) -> None:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            row = session.get(AssessmentSessionRow, _as_uuid(state.session_id))
            if row is None:
                raise KeyError(state.session_id)
            row.used_question_ids = list(state.used_question_ids)
            row.asked_signatures = list(state.asked_signatures)
            row.history = [item.model_dump(mode="json") for item in state.history]
            row.last_state = state.last_state.model_dump(mode="json") if state.last_state else None
            row.last_action = state.last_action.model_dump(mode="json") if state.last_action else None
            row.questions_asked = state.questions_asked
            row.session_kind = state.session_kind.value
            row.status = state.status.value
            row.terminate_reason = state.terminate_reason
            row.allowed_question_types = [t.value for t in state.allowed_question_types]
            row.scope_chapters = list(state.scope_chapters)
            row.elo_rating = state.elo_rating
            row.bkt_snapshot = state.bkt_snapshot
            row.ai_analysis = state.ai_analysis
            row.updated_at = now
            if state.status in (SessionStatus.COMPLETED, SessionStatus.TERMINATED, SessionStatus.FAILED):
                if row.ended_at is None:
                    row.ended_at = now
            session.commit()

    def list_for_user(self, user_id: str, *, limit: int = 50) -> list[SessionState]:
        with self._session_factory() as session:
            rows = session.execute(
                select(AssessmentSessionRow)
                .where(AssessmentSessionRow.user_id == user_id)
                .order_by(AssessmentSessionRow.started_at.desc())
                .limit(max(1, limit))
            ).scalars().all()
            return [_to_domain(row) for row in rows]

    def served_question_ids(self, user_id: str) -> list[str]:
        with self._session_factory() as session:
            rows = session.execute(
                select(ServedQuestionRow.question_id).where(ServedQuestionRow.user_id == user_id)
            ).scalars().all()
            return [str(qid) for qid in rows]

    def mark_served(
        self,
        *,
        user_id: str,
        question_id: str,
        session_id: str,
        topic_id: str = "",
        source: str = "bank",
    ) -> None:
        self.ensure_user(user_id)
        row = ServedQuestionRow(
            user_id=user_id,
            question_id=question_id,
            session_id=_as_uuid(session_id),
            topic_id=topic_id or "",
            source=source,
            served_at=datetime.now(timezone.utc),
        )
        with self._session_factory() as session:
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()

    def record_attempt(
        self,
        attempt: AttemptRecord,
        *,
        user_id: str,
        session_id: str,
        topic_id: str = "",
        similarity_score: float | None = None,
        distractor_tag: str | None = None,
        distractor_label: str | None = None,
    ) -> None:
        self.ensure_user(user_id)
        row = AttemptRow(
            id=uuid4(),
            user_id=user_id,
            session_id=_as_uuid(session_id),
            question_id=attempt.question_id,
            topic_id=topic_id or "",
            is_correct=attempt.is_correct,
            accuracy_score=attempt.accuracy_score,
            similarity_score=similarity_score,
            distractor_tag=distractor_tag or attempt.distractor_tag,
            distractor_label=distractor_label or attempt.distractor_label,
            error_category=attempt.error_category,
            missing_keywords=attempt.missing_keywords,
            detailed_explanation=attempt.detailed_explanation,
            missed_blanks=attempt.missed_blanks,
            concept_explanation=attempt.concept_explanation,
            student_answer=attempt.student_answer,
            trace=attempt.model_dump(mode="json"),
            answered_at=attempt.asked_at,
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()
