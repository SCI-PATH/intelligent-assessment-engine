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


class CreateSessionRequest(BaseModel):
    chapter_name: str
    grade: int = 6
    user_id: str | None = None


class SessionResponse(BaseModel):
    session_id: str
    user_id: str
    scope_chapter: str
    questions_asked: int
    max_questions: int


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
    """The 'RL X-ray' shown in the right-hand Streamlit panel."""

    state: RlState
    action: ActionTelemetry
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
    grade: int
    chapters: list[str]
    max_questions: int


class TeacherTopicItem(BaseModel):
    grade: int
    topic_id: str
    chapter_title: str
    skill: str
    chapter_number: int | None = None
    domain: str = ""
    concept_code: str = ""


class TeacherTopicsResponse(BaseModel):
    grade: int
    topics: list[TeacherTopicItem]


class GenerateQuestionsRequest(BaseModel):
    topic_id: str
    skill: str | None = None
    dok_level: int = Field(default=2, ge=1, le=4)
    question_type: QuestionType = QuestionType.MCQ
    count: int = Field(default=1, ge=1, le=8)


class GenerateQuestionsResponse(BaseModel):
    created: int
    questions: list[Question]


class TeacherQuestionListResponse(BaseModel):
    questions: list[Question]


class CreateTeacherQuestionRequest(BaseModel):
    grade: int = 6
    chapter_name: str = ""
    topic_id: str
    skill: str = ""
    dok_level: int = Field(ge=1, le=4)
    question_type: QuestionType
    payload: QuestionPayload
    sub_concept: str = ""


class PlacementSurveyRequest(BaseModel):
    user_id: str
    grade: int = Field(ge=6, le=9)
    completed_chapters_count: int = Field(ge=0)
    past_grade_marks_range: PastGradeMarksRange


class PlacementQuizItem(BaseModel):
    id: str
    chapter_name: str
    topic_id: str = ""
    skill: str = ""
    dok_level: int
    question_type: QuestionType
    grade: int
    prompt: dict


class PlacementQuizResponse(BaseModel):
    grade: int
    count: int
    questions: list[PlacementQuizItem]


class PlacementEvaluateRequest(BaseModel):
    user_id: str
    grade: int = Field(ge=6, le=9)
    completed_chapters_count: int = Field(ge=0)
    past_grade_marks_range: PastGradeMarksRange
    quiz_correct: int = Field(ge=0)
    quiz_total: int = Field(default=10, ge=1, le=50)
