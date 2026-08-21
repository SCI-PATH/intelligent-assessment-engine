"""SQLAlchemy mappings for ``question_engine`` tables."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class QuestionRow(Base):
    __tablename__ = "questions"
    __table_args__ = {"schema": "question_engine"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_name: Mapped[str] = mapped_column(Text, nullable=False)
    sub_concept: Mapped[str] = mapped_column(Text, nullable=False, default="")
    topic_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    skill: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dok_level: Mapped[int] = mapped_column(Integer, nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    chunk_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="ai")
    rejection_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rejection_confirmed_ai: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    rejection_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AnalyticsEventRow(Base):
    __tablename__ = "analytics_events"
    __table_args__ = {"schema": "question_engine"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    topic_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    question_id: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    distractor_tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    distractor_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    missing_keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    detailed_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    missed_blanks: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    concept_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_time_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    difficulty_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subtopic_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    chosen_distractor_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "question_engine"}

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_chapters_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    past_grade_marks_range: Mapped[str | None] = mapped_column(String(16), nullable=True)
    placement_category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    placement_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    role: Mapped[str | None] = mapped_column(String(16), nullable=True, default="student")
    class_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    study_hours_per_week: Mapped[float | None] = mapped_column(Float, nullable=True)
    self_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    science_self_efficacy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prerequisite_ready_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_chapter_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    initial_category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    initial_category_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlacementEvaluationRow(Base):
    __tablename__ = "placement_evaluations"
    __table_args__ = {"schema": "question_engine"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_chapters_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    past_grade_marks_range: Mapped[str] = mapped_column(String(16), nullable=False)
    quiz_correct: Mapped[int] = mapped_column(Integer, nullable=False)
    quiz_total: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    quiz_score: Mapped[float] = mapped_column(Float, nullable=False)
    past_score: Mapped[float] = mapped_column(Float, nullable=False)
    weighted_score: Mapped[float] = mapped_column(Float, nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AssessmentSessionRow(Base):
    __tablename__ = "assessment_sessions"
    __table_args__ = {"schema": "question_engine"}

    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    topic_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_chapter: Mapped[str] = mapped_column(Text, nullable=False)
    used_question_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    asked_signatures: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    last_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_action: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    questions_asked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    session_kind: Mapped[str | None] = mapped_column(String(32), nullable=True, default="diagnostic")
    status: Mapped[str | None] = mapped_column(String(16), nullable=True, default="active")
    terminate_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_question_types: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    scope_chapters: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    elo_rating: Mapped[float | None] = mapped_column(Float, nullable=True, default=1000.0)
    bkt_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AmplitudeAttemptRow(Base):
    __tablename__ = "amplitude_attempts"
    __table_args__ = {"schema": "question_engine"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_chapters_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    past_grade_marks_range: Mapped[str] = mapped_column(String(16), nullable=False)
    study_hours_per_week: Mapped[float | None] = mapped_column(Float, nullable=True)
    self_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    science_self_efficacy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prerequisite_ready_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_chapter_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    question_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    answers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    quiz_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quiz_total: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    quiz_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    history_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    weighted_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AmplitudeFixedItemRow(Base):
    __tablename__ = "amplitude_fixed_items"
    __table_args__ = {"schema": "question_engine"}

    grade: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(Text, nullable=False)


class AmplitudeQuestionRow(Base):
    """Dedicated Amplitude placement items (exactly 10 per grade)."""

    __tablename__ = "amplitude_questions"
    __table_args__ = {"schema": "question_engine"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    topic_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chapter_name: Mapped[str] = mapped_column(Text, nullable=False)
    sub_concept: Mapped[str] = mapped_column(Text, nullable=False, default="")
    skill: Mapped[str] = mapped_column(Text, nullable=False, default="")
    baseline_level: Mapped[int] = mapped_column(Integer, nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    chunk_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="approved")
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="amplitude")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ServedQuestionRow(Base):
    __tablename__ = "served_questions"
    __table_args__ = {"schema": "question_engine"}

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    question_id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    topic_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="bank")
    served_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AttemptRow(Base):
    __tablename__ = "attempts"
    __table_args__ = {"schema": "question_engine"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    question_id: Mapped[str] = mapped_column(Text, nullable=False)
    topic_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    accuracy_score: Mapped[float] = mapped_column(Float, nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    distractor_tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    distractor_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    missing_keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    detailed_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    missed_blanks: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    concept_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trace: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
