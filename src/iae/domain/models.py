"""Domain models shared across the application.

These types are intentionally framework-agnostic. They are the contract spoken
by the application layer (`iae.application`) and the protocols in
`iae.domain.protocols`. Infrastructure adapters convert to and from them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, AliasChoices

RuleTraceCategory = Literal["dok", "type", "cold_start"]


class TraceCondition(BaseModel):
    """One evaluated predicate shown in the adaptive decision trace."""

    label: str
    required: bool = True
    met: bool | None = None
    observed: str = ""


class RuleTrace(BaseModel):
    """Structured IF/THEN explanation for one policy branch (DOK or question type)."""

    rule_id: str
    title: str
    category: RuleTraceCategory
    pedagogy_tag: str = ""
    conditions: list[TraceCondition] = Field(default_factory=list)
    outcome: str = ""


class QuestionType(str, Enum):
    MCQ = "MCQ"
    SHORT_ANSWER = "ShortAnswer"
    MULTI_BLANK = "MultiBlank"
    TRUE_FALSE = "TrueFalse"


class QuestionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class QuestionOrigin(str, Enum):
    AI = "ai"
    TEACHER = "teacher"
    AMPLITUDE = "amplitude"


class ShortAnswerErrorCategory(str, Enum):
    NO_ERROR = "NO_ERROR"
    SPELLING_GRAMMAR_ERROR = "SPELLING_GRAMMAR_ERROR"
    MISSING_KEYWORDS = "MISSING_KEYWORDS"
    CONCEPTUAL_MISCONCEPTION = "CONCEPTUAL_MISCONCEPTION"
    COMPLETELY_IRRELEVANT = "COMPLETELY_IRRELEVANT"


class MultiBlankErrorCategory(str, Enum):
    NO_ERROR = "NO_ERROR"
    PARTIAL_MASTERY = "PARTIAL_MASTERY"
    FULL_MISCONCEPTION = "FULL_MISCONCEPTION"


class DistractorTag(str, Enum):
    NEAR_MISS = "NEAR_MISS"
    MISCONCEPTION = "MISCONCEPTION"
    COMPLETE_MISS = "COMPLETE_MISS"


DokLevel = Annotated[int, Field(ge=1, le=4)]


class SubConcept(BaseModel):
    id: str
    chapter_name: str
    name: str
    description: str
    grade: int = 6


class Chunk(BaseModel):
    """A retrieval unit produced by the ingest pipeline."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str
    chapter_name: str
    sub_concept: str
    page_start: int
    page_end: int
    source: str
    grade: int = 6
    topic_id: str = ""
    skill: str = ""


class OptionDiagnostic(BaseModel):
    """Misconception metadata for one wrong MCQ option (stored in bank payload)."""

    distractor_tag: DistractorTag
    distractor_label: str


class MCQPayload(BaseModel):
    type: Literal[QuestionType.MCQ] = QuestionType.MCQ
    question: str
    options: dict[str, str]
    correct_answer: str
    # Wrong options only — keyed by letter after shuffle.
    option_diagnostics: dict[str, OptionDiagnostic] = Field(default_factory=dict)


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
    # Diagnostics for the incorrect polarity (Component 4 contract field names).
    distractor_tag: DistractorTag | None = None
    distractor_label: str | None = None


QuestionPayload = Annotated[
    Union[MCQPayload, ShortAnswerPayload, MultiBlankPayload, TrueFalsePayload],
    Field(discriminator="type"),
]


class PastGradeMarksRange(str, Enum):
    BELOW_50 = "BELOW_50"
    BAND_50_75 = "50_75"
    ABOVE_75 = "ABOVE_75"


class PlacementCategory(str, Enum):
    """Legacy placement labels (still accepted on read)."""

    WEAK = "WEAK"
    AVERAGE = "AVERAGE"
    ADVANCED = "ADVANCED"


class AmplitudeCategory(str, Enum):
    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class UserRole(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"


class SessionKind(str, Enum):
    DIAGNOSTIC = "diagnostic"
    CUSTOMIZABLE = "customizable"
    POST_LESSON = "post_lesson"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    TERMINATED = "terminated"
    FAILED = "failed"


class RejectionReason(str, Enum):
    FACTUAL_ERROR = "FACTUAL_ERROR"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    POOR_PHRASING = "POOR_PHRASING"
    TOO_EASY = "TOO_EASY"
    TOO_HARD = "TOO_HARD"
    OTHER = "OTHER"


class Question(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        validation_alias=AliasChoices("id", "_id"),
        serialization_alias="id",
    )
    chapter_name: str
    sub_concept: str
    dok_level: DokLevel
    question_type: QuestionType
    payload: QuestionPayload
    chunk_ids: list[str] = Field(default_factory=list)
    grade: int = 6
    topic_id: str = ""
    skill: str = ""
    status: QuestionStatus = QuestionStatus.PENDING
    origin: QuestionOrigin = QuestionOrigin.AI
    rejection_reason: RejectionReason | None = None
    rejection_confirmed_ai: bool = False
    rejection_notes: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RlState(BaseModel):
    """Inputs the policy reads before choosing the next item."""

    current_chapter: str
    time_taken: float = 0.0
    response_time_seconds: float = 0.0
    accuracy_score: float = 0.0
    streak: int = 0
    current_difficulty: DokLevel = 2
    last_question_type: QuestionType | None = None
    current_sub_concept: str | None = None


class RlAction(BaseModel):
    target_chapter: str
    next_difficulty_level: DokLevel
    next_question_type: QuestionType
    next_sub_concept: str
    rule_triggered: str = "cold-start"
    dok_reason: str = ""
    question_type_reason: str = ""
    dok_summary: str = ""
    type_summary: str = ""
    dok_trace: RuleTrace | None = None
    type_trace: RuleTrace | None = None
    estimated_theta: float = 0.0
    item_b: float = 0.0
    previous_response_time_seconds: float = 0.0
    rapid_guessing_detected: bool = False
    format_simplification_triggered: bool = False


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
    reasoning: str = ""
    adaptive_decision: str = ""
    decision_rule_triggered: str = ""
    decision_dok_reason: str = ""
    decision_question_type_reason: str = ""
    decision_prev_dok: DokLevel | None = None
    decision_target_dok: DokLevel | None = None
    decision_rolling_accuracy: float | None = None
    decision_last_accuracy: float | None = None
    decision_last_response_time_seconds: float | None = None
    decision_dok_trace: RuleTrace | None = None
    decision_type_trace: RuleTrace | None = None
    time_taken_seconds: float = 0.0
    asked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_category: str | None = None
    missing_keywords: list[str] | None = None
    detailed_explanation: str | None = None
    missed_blanks: dict[str, str] | None = None
    concept_explanation: str | None = None
    distractor_tag: str | None = None
    distractor_label: str | None = None


class SessionState(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str = Field(default_factory=lambda: str(uuid4()))
    scope_chapter: str
    used_question_ids: list[str] = Field(default_factory=list)
    asked_signatures: list[str] = Field(default_factory=list)
    history: list[AttemptRecord] = Field(default_factory=list)
    last_state: RlState | None = None
    last_action: RlAction | None = None
    questions_asked: int = 0
    grade: int = 6
    max_questions: int = 5
    session_kind: SessionKind = SessionKind.DIAGNOSTIC
    status: SessionStatus = SessionStatus.ACTIVE
    terminate_reason: str | None = None
    allowed_question_types: list[QuestionType] = Field(default_factory=list)
    scope_chapters: list[str] = Field(default_factory=list)
    elo_rating: float = 1000.0
    bkt_snapshot: dict | None = None
    ai_analysis: dict | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GradeResult(BaseModel):
    accuracy_score: float = Field(ge=0.0, le=1.0)
    is_correct: bool
    feedback: str = ""
    reasoning: str = ""
    error_category: str | None = None
    missing_keywords: list[str] | None = None
    detailed_explanation: str | None = None
    missed_blanks: dict[str, str] | None = None
    concept_explanation: str | None = None
    distractor_tag: str | None = None
    distractor_label: str | None = None


class StudentProfile(BaseModel):
    user_id: str
    grade: int | None = None
    completed_chapters_count: int | None = None
    completed_chapter_ids: list[str] = Field(default_factory=list)
    past_grade_marks_range: PastGradeMarksRange | None = None
    placement_category: PlacementCategory | AmplitudeCategory | None = None
    placement_score: float | None = None
    role: UserRole = UserRole.STUDENT
    class_code: str | None = None
    display_name: str | None = None
    study_hours_per_week: float | None = None
    self_confidence: int | None = None
    science_self_efficacy: int | None = None
    prerequisite_ready_count: int | None = None
    initial_category: AmplitudeCategory | None = None
    initial_category_score: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AmplitudeEvaluation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    grade: int
    completed_chapters_count: int = 0
    completed_chapter_ids: list[str] = Field(default_factory=list)
    past_grade_marks_range: PastGradeMarksRange
    study_hours_per_week: float | None = None
    self_confidence: int | None = None
    science_self_efficacy: int | None = None
    prerequisite_ready_count: int | None = None
    question_ids: list[str] = Field(default_factory=list)
    answers: dict[str, str] = Field(default_factory=dict)
    quiz_correct: int = 0
    quiz_total: int = 10
    quiz_score: float = 0.0
    history_score: float = 0.0
    weighted_score: float = 0.0
    category: AmplitudeCategory
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlacementEvaluation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    grade: int
    completed_chapters_count: int = 0
    past_grade_marks_range: PastGradeMarksRange
    quiz_correct: int
    quiz_total: int = 10
    quiz_score: float
    past_score: float
    weighted_score: float
    category: PlacementCategory | AmplitudeCategory
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
