"""Domain models shared across the application.

These types are intentionally framework-agnostic. They are the contract spoken
by the application layer (`iae.application`) and the protocols in
`iae.core.protocols`. Infrastructure adapters convert to and from them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class QuestionType(str, Enum):
    MCQ = "MCQ"
    SHORT_ANSWER = "ShortAnswer"
    MULTI_BLANK = "MultiBlank"
    TRUE_FALSE = "TrueFalse"


DokLevel = Annotated[int, Field(ge=1, le=4)]


class SubConcept(BaseModel):
    id: str
    chapter_name: str
    name: str
    description: str


class Chunk(BaseModel):
    """A retrieval unit produced by the ingest pipeline."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str
    chapter_name: str
    sub_concept: str
    page_start: int
    page_end: int
    source: str = "grade_6_science.pdf"


class MCQPayload(BaseModel):
    type: Literal[QuestionType.MCQ] = QuestionType.MCQ
    question: str
    options: dict[str, str]
    correct_answer: str


class ShortAnswerPayload(BaseModel):
    type: Literal[QuestionType.SHORT_ANSWER] = QuestionType.SHORT_ANSWER
    question: str
    ideal_answer: str
    keywords: list[str]


class MultiBlankPayload(BaseModel):
    """Cloze paragraph with 3-5 ordered blanks rendered as ``___``."""

    type: Literal[QuestionType.MULTI_BLANK] = QuestionType.MULTI_BLANK
    paragraph: str
    answers: list[str]


class TrueFalsePayload(BaseModel):
    type: Literal[QuestionType.TRUE_FALSE] = QuestionType.TRUE_FALSE
    question: str
    correct_answer: Literal["True", "False"]


QuestionPayload = Annotated[
    Union[MCQPayload, ShortAnswerPayload, MultiBlankPayload, TrueFalsePayload],
    Field(discriminator="type"),
]


class Question(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
    chapter_name: str
    sub_concept: str
    dok_level: DokLevel
    question_type: QuestionType
    payload: QuestionPayload
    chunk_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RlState(BaseModel):
    """Inputs the policy reads before choosing the next item."""

    current_chapter: str
    time_taken: float = 0.0
    accuracy_score: float = 0.0
    streak: int = 0
    current_difficulty: DokLevel = 2
    current_sub_concept: str | None = None


class RlAction(BaseModel):
    target_chapter: str
    next_difficulty_level: DokLevel
    next_question_type: QuestionType
    next_sub_concept: str


class AttemptRecord(BaseModel):
    question_id: str
    question_type: QuestionType
    chapter_name: str
    sub_concept: str
    dok_level: DokLevel
    student_answer: str
    accuracy_score: float
    is_correct: bool
    feedback: str = ""
    time_taken_seconds: float = 0.0
    asked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionState(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
    scope_chapter: str
    used_question_ids: list[str] = Field(default_factory=list)
    asked_signatures: list[str] = Field(default_factory=list)
    history: list[AttemptRecord] = Field(default_factory=list)
    last_state: RlState | None = None
    last_action: RlAction | None = None
    questions_asked: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GradeResult(BaseModel):
    accuracy_score: float = Field(ge=0.0, le=1.0)
    is_correct: bool
    feedback: str = ""
