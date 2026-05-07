"""HTTP request/response models.

Kept separate from ``iae.core.models`` so the API surface can evolve without
touching the domain layer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from iae.core.models import (
    AttemptRecord,
    GradeResult,
    Question,
    RlAction,
    RlState,
)


class CreateSessionRequest(BaseModel):
    chapter_name: str


class SessionResponse(BaseModel):
    session_id: str
    scope_chapter: str
    questions_asked: int
    max_questions: int


class TelemetryPayload(BaseModel):
    """The 'RL X-ray' shown in the right-hand Streamlit panel."""

    state: RlState
    action: RlAction
    rolling_accuracy: float = Field(ge=0.0, le=1.0)
    questions_asked: int


class NextQuestionResponse(BaseModel):
    question: Question
    telemetry: TelemetryPayload


class SubmitAnswerRequest(BaseModel):
    question_id: str
    student_answer: str
    time_taken_seconds: float = 0.0


class SubmitAnswerResponse(BaseModel):
    grade: GradeResult
    questions_asked: int
    is_complete: bool


class ResultsResponse(BaseModel):
    scope_chapter: str
    questions_asked: int
    correct_count: int
    raw_accuracy: float
    history: list[AttemptRecord]


class ChaptersResponse(BaseModel):
    chapters: list[str]
    max_questions: int
