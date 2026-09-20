"""``IQuestionRepository`` backed by PostgreSQL ``question_engine.questions``."""

from __future__ import annotations

from typing import Iterable
from uuid import UUID

from sqlalchemy import Select, Text, cast, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from iae.domain.models import Question, QuestionOrigin, QuestionStatus, QuestionType, RejectionReason
from iae.infrastructure.postgres.orm import QuestionRow


def _parse_rejection(raw: str | None) -> RejectionReason | None:
    if not raw:
        return None
    try:
        return RejectionReason(raw)
    except ValueError:
        return None


def _to_domain(row: QuestionRow) -> Question:
    return Question(
        id=str(row.id),
        chapter_name=row.chapter_name,
        sub_concept=row.sub_concept,
        dok_level=row.dok_level,
        question_type=QuestionType(row.question_type),
        payload=row.payload,
        chunk_ids=list(row.chunk_ids or []),
        grade=row.grade,
        topic_id=row.topic_id or "",
        skill=row.skill or "",
        status=QuestionStatus(row.status),
        origin=QuestionOrigin(row.origin),
        rejection_reason=_parse_rejection(row.rejection_reason),
        rejection_confirmed_ai=bool(row.rejection_confirmed_ai),
        rejection_notes=row.rejection_notes,
        created_at=row.created_at,
    )


def _to_row(question: Question) -> QuestionRow:
    return QuestionRow(
        id=UUID(question.id),
        grade=question.grade,
        chapter_name=question.chapter_name,
        sub_concept=question.sub_concept,
        topic_id=question.topic_id or "",
        skill=question.skill or "",
        dok_level=question.dok_level,
        question_type=question.question_type.value,
        payload=question.payload.model_dump(mode="json"),
        chunk_ids=list(question.chunk_ids or []),
        status=question.status.value,
        origin=question.origin.value,
        rejection_reason=question.rejection_reason.value if question.rejection_reason else None,
        rejection_confirmed_ai=question.rejection_confirmed_ai,
        rejection_notes=question.rejection_notes,
        created_at=question.created_at,
    )


class PostgresQuestionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def insert_many(self, questions: Iterable[Question]) -> int:
        rows = [_to_row(q) for q in questions]
        if not rows:
            return 0
        with self._session_factory() as session:
            session.add_all(rows)
            session.commit()
        return len(rows)

    def find_one_unused(
        self,
        *,
        chapter_name: str,
        sub_concept: str,
        dok_level: int,
        question_type: QuestionType,
        excluded_ids: list[str],
        topic_id: str = "",
        exclude_sub_concepts: list[str] | None = None,
    ) -> Question | None:
        relaxations: list[dict] = []
        if topic_id:
            relaxations.extend(
                [
                    {
                        "chapter_name": chapter_name,
                        "topic_id": topic_id,
                        "dok_level": dok_level,
                        "question_type": question_type.value,
                    },
                    {
                        "chapter_name": chapter_name,
                        "topic_id": topic_id,
                        "dok_level": dok_level,
                    },
                    {
                        "chapter_name": chapter_name,
                        "topic_id": topic_id,
                    },
                ]
            )
        if sub_concept:
            relaxations.extend(
                [
                    {
                        "chapter_name": chapter_name,
                        "sub_concept": sub_concept,
                        "dok_level": dok_level,
                        "question_type": question_type.value,
                    },
                    {
                        "chapter_name": chapter_name,
                        "sub_concept": sub_concept,
                        "dok_level": dok_level,
                    },
                ]
            )
        relaxations.extend(
            [
                {
                    "chapter_name": chapter_name,
                    "dok_level": dok_level,
                    "question_type": question_type.value,
                },
                {
                    "chapter_name": chapter_name,
                    "dok_level": dok_level,
                },
                {"chapter_name": chapter_name},
            ]
        )
        blocked_subs = [s for s in (exclude_sub_concepts or []) if s and str(s).strip()]
        with self._session_factory() as session:
            for filters in relaxations:
                stmt = self._approved_query(
                    filters,
                    excluded_ids,
                    exclude_sub_concepts=blocked_subs,
                ).order_by(func.random()).limit(1)
                row = session.execute(stmt).scalar_one_or_none()
                if row is not None:
                    return _to_domain(row)
        return None

    def list_approved_for_chapters(
        self,
        *,
        chapter_names: list[str],
        question_types: list[QuestionType] | None = None,
        grade: int | None = None,
        limit: int = 2000,
    ) -> list[Question]:
        """One round-trip preload for quiz-session in-memory DDA selection."""
        names = [n for n in chapter_names if n and str(n).strip()]
        if not names:
            return []
        stmt = (
            select(QuestionRow)
            .where(QuestionRow.status == QuestionStatus.APPROVED.value)
            .where(QuestionRow.chapter_name.in_(names))
            .limit(max(1, limit))
        )
        if grade is not None:
            stmt = stmt.where(QuestionRow.grade == grade)
        if question_types:
            stmt = stmt.where(
                QuestionRow.question_type.in_([t.value for t in question_types])
            )
        with self._session_factory() as session:
            rows = session.execute(stmt).scalars().all()
            return [_to_domain(row) for row in rows]

    def count_matching(
        self,
        *,
        chapter_name: str | None = None,
        sub_concept: str | None = None,
        dok_level: int | None = None,
        question_type: QuestionType | None = None,
    ) -> int:
        filters: dict = {"status": QuestionStatus.APPROVED.value}
        if chapter_name is not None:
            filters["chapter_name"] = chapter_name
        if sub_concept is not None:
            filters["sub_concept"] = sub_concept
        if dok_level is not None:
            filters["dok_level"] = dok_level
        if question_type is not None:
            filters["question_type"] = question_type.value
        with self._session_factory() as session:
            stmt = select(func.count()).select_from(QuestionRow).filter_by(**filters)
            return int(session.execute(stmt).scalar_one())

    def get(self, question_id: str) -> Question | None:
        try:
            pk = UUID(question_id)
        except ValueError:
            return None
        with self._session_factory() as session:
            row = session.get(QuestionRow, pk)
            return _to_domain(row) if row is not None else None

    def list_questions(
        self,
        *,
        status: QuestionStatus | None = None,
        topic_id: str | None = None,
        grade: int | None = None,
        grades: list[int] | None = None,
        dok_level: int | None = None,
        question_type: QuestionType | None = None,
        limit: int = 100,
        offset: int = 0,
        origin: QuestionOrigin | None = None,
        q: str | None = None,
        topic_id_prefix: str | None = None,
    ) -> list[Question]:
        questions, _total = self.list_page(
            status=status,
            topic_id=topic_id,
            grade=grade,
            grades=grades,
            dok_level=dok_level,
            question_type=question_type,
            limit=limit,
            offset=offset,
            origin=origin,
            q=q,
            topic_id_prefix=topic_id_prefix,
        )
        return questions

    def list_page(
        self,
        *,
        status: QuestionStatus | None = None,
        topic_id: str | None = None,
        grade: int | None = None,
        grades: list[int] | None = None,
        dok_level: int | None = None,
        question_type: QuestionType | None = None,
        limit: int = 100,
        offset: int = 0,
        origin: QuestionOrigin | None = None,
        q: str | None = None,
        topic_id_prefix: str | None = None,
    ) -> tuple[list[Question], int]:
        cap = max(1, min(int(limit), 500))
        skip = max(0, int(offset))
        filters = self._list_filters(
            status=status,
            topic_id=topic_id,
            grade=grade,
            grades=grades,
            dok_level=dok_level,
            question_type=question_type,
            origin=origin,
            q=q,
            topic_id_prefix=topic_id_prefix,
        )
        count_stmt = select(func.count()).select_from(QuestionRow)
        list_stmt = select(QuestionRow).order_by(QuestionRow.created_at.desc())
        for clause in filters:
            count_stmt = count_stmt.where(clause)
            list_stmt = list_stmt.where(clause)
        list_stmt = list_stmt.offset(skip).limit(cap)
        with self._session_factory() as session:
            total = int(session.execute(count_stmt).scalar_one())
            rows = session.execute(list_stmt).scalars().all()
            return [_to_domain(row) for row in rows], total

    @staticmethod
    def _list_filters(
        *,
        status: QuestionStatus | None,
        topic_id: str | None,
        grade: int | None,
        grades: list[int] | None,
        dok_level: int | None,
        question_type: QuestionType | None,
        origin: QuestionOrigin | None,
        q: str | None,
        topic_id_prefix: str | None,
    ) -> list:
        clauses = []
        if status is not None:
            clauses.append(QuestionRow.status == status.value)
        if topic_id is not None:
            clauses.append(QuestionRow.topic_id == topic_id)
        if grade is not None:
            clauses.append(QuestionRow.grade == grade)
        if grades:
            clauses.append(QuestionRow.grade.in_(grades))
        if dok_level is not None:
            clauses.append(QuestionRow.dok_level == dok_level)
        if question_type is not None:
            clauses.append(QuestionRow.question_type == question_type.value)
        if origin == QuestionOrigin.TEACHER:
            clauses.append(QuestionRow.origin == QuestionOrigin.TEACHER.value)
        elif origin is not None:
            clauses.append(QuestionRow.origin != QuestionOrigin.TEACHER.value)
        prefix = (topic_id_prefix or "").strip().upper()
        if prefix:
            clauses.append(QuestionRow.topic_id.ilike(f"{prefix}_%"))
        needle = (q or "").strip()
        if needle:
            like = f"%{needle}%"
            clauses.append(
                or_(
                    QuestionRow.chapter_name.ilike(like),
                    QuestionRow.topic_id.ilike(like),
                    QuestionRow.skill.ilike(like),
                    cast(QuestionRow.payload, Text).ilike(like),
                )
            )
        return clauses

    def set_status(self, question_id: str, status: QuestionStatus) -> Question | None:
        try:
            pk = UUID(question_id)
        except ValueError:
            return None
        with self._session_factory() as session:
            row = session.get(QuestionRow, pk)
            if row is None:
                return None
            row.status = status.value
            if status != QuestionStatus.REJECTED:
                row.rejection_reason = None
                row.rejection_confirmed_ai = False
                row.rejection_notes = None
            session.commit()
            session.refresh(row)
            return _to_domain(row)

    def reject(
        self,
        question_id: str,
        *,
        reason: RejectionReason,
        notes: str | None = None,
        confirmed_ai: bool = False,
    ) -> Question | None:
        try:
            pk = UUID(question_id)
        except ValueError:
            return None
        with self._session_factory() as session:
            row = session.get(QuestionRow, pk)
            if row is None:
                return None
            row.status = QuestionStatus.REJECTED.value
            row.rejection_reason = reason.value
            row.rejection_notes = notes
            row.rejection_confirmed_ai = confirmed_ai
            session.commit()
            session.refresh(row)
            return _to_domain(row)

    @staticmethod
    def _approved_query(
        filters: dict,
        excluded_ids: list[str],
        *,
        exclude_sub_concepts: list[str] | None = None,
    ) -> Select[tuple[QuestionRow]]:
        stmt = select(QuestionRow).filter_by(status=QuestionStatus.APPROVED.value, **filters)
        excluded: list[UUID] = []
        for qid in excluded_ids:
            try:
                excluded.append(UUID(qid))
            except ValueError:
                continue
        if excluded:
            stmt = stmt.where(QuestionRow.id.not_in(excluded))
        # Soft variety: avoid recently used sub_concepts when callers request it.
        blocked = [s.strip() for s in (exclude_sub_concepts or []) if s and str(s).strip()]
        if blocked:
            stmt = stmt.where(QuestionRow.sub_concept.not_in(blocked))
        return stmt
