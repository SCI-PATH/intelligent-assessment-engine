"""HTTP request/response models for the Assessment Engine API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from iae.domain.models import (
    GradeResult,
    PastGradeMarksRange,
    Question,
    QuestionPayload,
    QuestionType,
    RejectionReason,
)


class ErrorDetail(BaseModel):
    detail: str = Field(examples=["Session not found."])


# --- Amplitude / placement ---


class PlacementQuizItem(BaseModel):
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


class AmplitudeSurveyRequest(BaseModel):
    user_id: str = Field(
        default="mock-student-class-a",
        examples=["mock-student-class-a", "mock-student-unassigned"],
    )
    grade: int = Field(ge=6, le=9)
    completed_chapters_count: int = Field(ge=0)
    past_grade_marks_range: PastGradeMarksRange
    study_hours_per_week: float | None = Field(default=None, ge=0, le=40)
    self_confidence: int | None = Field(default=None, ge=1, le=5)


class AmplitudeEvaluateRequest(BaseModel):
    user_id: str
    grade: int = Field(ge=6, le=9)
    completed_chapters_count: int = Field(ge=0)
    past_grade_marks_range: PastGradeMarksRange
    study_hours_per_week: float | None = Field(default=None, ge=0, le=40)
    self_confidence: int | None = Field(default=None, ge=1, le=5)
    answers: dict[str, str] = Field(
        description="Map of question_id → student answer for the fixed 10 items."
    )


class AmplitudeCategoryResponse(BaseModel):
    student_id: str
    initial_category: str | None = None
    initial_category_score: float | None = None
    placement_category: str | None = None


# --- Quizzes ---


class SubmitAnswerRequest(BaseModel):
    question_id: str
    student_answer: str = Field(examples=["B"])
    time_taken_seconds: float = Field(default=0.0, ge=0.0)


class CreateCustomizableQuizRequest(BaseModel):
    student_id: str = Field(default="mock-student-class-a", examples=["mock-student-class-a"])
    grade: int = Field(ge=6, le=9)
    chapters: list[str] = Field(
        min_length=1,
        description="Canonical chapter_ids from data/chapter_ids_g6_g9.csv (e.g. G6_C8).",
        examples=[["G6_C8", "G6_C7"]],
    )
    num_questions: int = Field(default=5, ge=1, le=30)
    question_types: list[QuestionType] | None = None


class TriggerPostLessonRequest(BaseModel):
    student_id: str = Field(default="mock-student-class-a", examples=["mock-student-class-a"])
    chapter_id: str = Field(examples=["G6_C8"])
    grade: int = Field(default=6, ge=6, le=9)


class TerminateSessionRequest(BaseModel):
    reason: str | None = "component_3_kill_switch"
    source: str = Field(default="component_3")


class QuizSessionResponse(BaseModel):
    session_id: str
    user_id: str
    scope_chapter: str
    scope_chapters: list[str] = Field(default_factory=list)
    session_kind: str
    status: str
    questions_asked: int
    max_questions: int
    elo_rating: float = 1000.0


class QuizNextResponse(BaseModel):
    question: Question
    elo_rating: float
    questions_asked: int
    max_questions: int
    target_dok: int | None = None
    target_topic_id: str | None = None
    target_question_type: str | None = None


class QuizAnswerResponse(BaseModel):
    grade: GradeResult
    questions_asked: int
    is_complete: bool
    elo_rating: float
    next_dok: int | None = None
    status: str


# --- Teacher ---


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
    topic_id: str = Field(examples=["G6_C7_MAG_POLES"])
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
    grade: int = Field(default=6, ge=6, le=9)
    chapter_name: str = ""
    topic_id: str
    skill: str = ""
    dok_level: int = Field(ge=1, le=4)
    question_type: QuestionType
    payload: QuestionPayload
    sub_concept: str = ""


class RejectQuestionRequest(BaseModel):
    reason: RejectionReason
    notes: str | None = None
