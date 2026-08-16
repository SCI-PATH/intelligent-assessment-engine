"""HTTP request/response models.

Kept separate from ``iae.core.models`` so the API surface can evolve without
touching the domain layer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from iae.core.models import (
    AttemptRecord,
    GradeResult,
    PastGradeMarksRange,
    Question,
    QuestionPayload,
    QuestionStatus,
    QuestionType,
    RlState,
    RuleTrace,
)


class ErrorDetail(BaseModel):
    """Standard FastAPI error body."""

    detail: str = Field(examples=["Session not found."])


class CreateSessionRequest(BaseModel):
    """Start an adaptive diagnostic session for one curriculum chapter."""

    chapter_name: str = Field(
        description="Exact curriculum chapter title for the chosen grade.",
        examples=["Magnets"],
    )
    grade: int = Field(default=6, ge=6, le=9, description="Student grade year (6–9).")
    user_id: str | None = Field(
        default=None,
        description="Optional stable student id. Auto-generated if omitted.",
        examples=["student-42"],
    )


class SessionResponse(BaseModel):
    session_id: str = Field(description="Use this id for `/next`, `/answer`, and `/results`.")
    user_id: str
    scope_chapter: str
    questions_asked: int = Field(description="How many items have already been served.")
    max_questions: int = Field(description="Session ends when questions_asked reaches this.")


class ActionTelemetry(BaseModel):
    target_chapter: str
    next_difficulty_level: int
    next_question_type: QuestionType
    next_sub_concept: str
    rule_triggered: str
    dok_reason: str
    question_type_reason: str
    dok_summary: str = ""
    type_summary: str = ""
    dok_trace: RuleTrace | None = None
    type_trace: RuleTrace | None = None
    estimated_theta: float
    item_b: float
    previous_response_time_seconds: float
    rapid_guessing_detected: bool
    format_simplification_triggered: bool


class TelemetryPayload(BaseModel):
    """Adaptive-policy X-ray returned with each next question."""

    state: RlState
    action: ActionTelemetry
    rolling_accuracy: float = Field(ge=0.0, le=1.0)
    questions_asked: int


class NextQuestionResponse(BaseModel):
    question: Question = Field(
        description=(
            "Full bank item including answer keys in `payload`. "
            "Do not render correct answers to students."
        )
    )
    telemetry: TelemetryPayload


class SubmitAnswerRequest(BaseModel):
    """Grade one student response inside an active session."""

    question_id: str = Field(description="Must match the question returned by `/next`.")
    student_answer: str = Field(
        description=(
            "MCQ: option letter (A–D). TrueFalse: `True`/`False`. "
            "ShortAnswer: free text. MultiBlank: answers joined as configured by the client "
            "(typically comma- or newline-separated)."
        ),
        examples=["B"],
    )
    time_taken_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="Client-measured response time; feeds rapid-guessing heuristics.",
    )


class SubmitAnswerResponse(BaseModel):
    grade: GradeResult = Field(description="Diagnostic grading result for this attempt.")
    questions_asked: int
    is_complete: bool = Field(description="True when the session has reached max_questions.")


class ResultsResponse(BaseModel):
    scope_chapter: str
    questions_asked: int
    correct_count: int
    raw_accuracy: float
    history: list[AttemptRecord]


class ChaptersResponse(BaseModel):
    grade: int
    chapters: list[str] = Field(description="Curriculum chapter titles for this grade.")
    max_questions: int


class TeacherTopicItem(BaseModel):
    grade: int
    topic_id: str = Field(examples=["G6_C7_MAG_POLES"])
    chapter_title: str
    skill: str
    chapter_number: int | None = None
    domain: str = ""
    concept_code: str = ""


class TeacherTopicsResponse(BaseModel):
    grade: int
    topics: list[TeacherTopicItem]


class GenerateQuestionsRequest(BaseModel):
    """Generate pending bank items from Chroma RAG for one Topic ID."""

    topic_id: str = Field(examples=["G6_C7_MAG_POLES"])
    skill: str | None = Field(
        default=None,
        description="Optional skill override; defaults to the Excel skill for the Topic ID.",
    )
    dok_level: int = Field(default=2, ge=1, le=4, description="Depth of Knowledge level 1–4.")
    question_type: QuestionType = QuestionType.MCQ
    count: int = Field(default=1, ge=1, le=8, description="How many items to generate.")


class GenerateQuestionsResponse(BaseModel):
    created: int
    questions: list[Question] = Field(description="New items stored as `pending` until approved.")


class TeacherQuestionListResponse(BaseModel):
    questions: list[Question]


class CreateTeacherQuestionRequest(BaseModel):
    """Manually insert a teacher-authored bank item (stored as pending)."""

    grade: int = Field(default=6, ge=6, le=9)
    chapter_name: str = ""
    topic_id: str
    skill: str = ""
    dok_level: int = Field(ge=1, le=4)
    question_type: QuestionType
    payload: QuestionPayload
    sub_concept: str = ""


class PlacementSurveyRequest(BaseModel):
    """Persist the student's self-report before the placement quiz."""

    user_id: str = Field(examples=["student-42"])
    grade: int = Field(ge=6, le=9)
    completed_chapters_count: int = Field(
        ge=0,
        description="How many chapters the student reports having completed this year.",
    )
    past_grade_marks_range: PastGradeMarksRange = Field(
        description="Self-reported prior marks band.",
        examples=[PastGradeMarksRange.BAND_50_75],
    )


class PlacementQuizItem(BaseModel):
    """Public quiz prompt — answer keys are stripped."""

    id: str
    chapter_name: str
    topic_id: str = ""
    skill: str = ""
    dok_level: int
    question_type: QuestionType
    grade: int
    prompt: dict = Field(description="Question payload without correct-answer fields.")


class PlacementQuizResponse(BaseModel):
    grade: int
    count: int
    questions: list[PlacementQuizItem]


class PlacementEvaluateRequest(BaseModel):
    """Compute and persist WEAK / AVERAGE / ADVANCED from quiz + past marks."""

    user_id: str
    grade: int = Field(ge=6, le=9)
    completed_chapters_count: int = Field(ge=0)
    past_grade_marks_range: PastGradeMarksRange
    quiz_correct: int = Field(ge=0, description="Number of placement-quiz items answered correctly.")
    quiz_total: int = Field(default=10, ge=1, le=50, description="Usually 10.")
