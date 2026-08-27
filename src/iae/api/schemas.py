"""HTTP request/response models for the Assessment Engine API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

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
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_id": "mock-student-class-a",
                    "grade": 7,
                    "completed_chapter_ids": [],
                    "past_grade_marks_range": "50_75",
                    "study_hours_per_week": 5.0,
                    "self_confidence": 3,
                    "science_self_efficacy": 4,
                    "prerequisite_ready_count": 3,
                }
            ]
        }
    )

    user_id: str = Field(
        default="mock-student-class-a",
        examples=["mock-student-class-a", "mock-student-unassigned"],
    )
    grade: int = Field(default=7, ge=6, le=9)
    past_grade_marks_range: PastGradeMarksRange = Field(
        default=PastGradeMarksRange.BAND_50_75,
        description="Mandatory usual / past science marks band.",
    )
    completed_chapter_ids: list[str] | None = Field(
        default_factory=list,
        description=(
            "Canonical chapter_ids for this grade (e.g. G6_C8). "
            "Send [] if the student has not completed any chapter yet. "
            "Omit only for legacy clients that send completed_chapters_count."
        ),
        examples=[[], ["G7_C1", "G7_C2"]],
    )
    completed_chapters_count: int | None = Field(
        default=None,
        ge=0,
        description="Legacy fallback when completed_chapter_ids is omitted.",
    )
    study_hours_per_week: float | None = Field(default=5.0, ge=0, le=40)
    self_confidence: int | None = Field(default=3, ge=1, le=5)
    science_self_efficacy: int | None = Field(
        default=4,
        ge=1,
        le=5,
        description="Bandura-style: I can figure out science questions even when they are new or a bit hard.",
    )
    prerequisite_ready_count: int | None = Field(
        default=3,
        ge=0,
        le=5,
        description="How many of the five prerequisite checklist items the student ticked.",
    )


class AmplitudeEvaluateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_id": "mock-student-class-a",
                    "grade": 7,
                    "completed_chapter_ids": [],
                    "past_grade_marks_range": "50_75",
                    "study_hours_per_week": 5.0,
                    "self_confidence": 3,
                    "science_self_efficacy": 4,
                    "prerequisite_ready_count": 3,
                    "answers": {
                        "REPLACE_WITH_QUESTION_ID_1": "A",
                        "REPLACE_WITH_QUESTION_ID_2": "True",
                    },
                }
            ]
        }
    )

    user_id: str = Field(default="mock-student-class-a")
    grade: int = Field(default=7, ge=6, le=9)
    past_grade_marks_range: PastGradeMarksRange = Field(
        default=PastGradeMarksRange.BAND_50_75,
    )
    completed_chapter_ids: list[str] | None = Field(default_factory=list)
    completed_chapters_count: int | None = Field(default=None, ge=0)
    study_hours_per_week: float | None = Field(default=5.0, ge=0, le=40)
    self_confidence: int | None = Field(default=3, ge=1, le=5)
    science_self_efficacy: int | None = Field(default=4, ge=1, le=5)
    prerequisite_ready_count: int | None = Field(default=3, ge=0, le=5)
    answers: dict[str, str] = Field(
        default_factory=dict,
        description="Map of question_id → student answer for the fixed 10 items. "
        "Paste real ids from GET /amplitude/quiz.",
    )


class AmplitudeCategoryResponse(BaseModel):
    student_id: str
    initial_category: str | None = None
    initial_category_score: float | None = None
    placement_category: str | None = None


# --- Quizzes ---


class SubmitAnswerRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "question_id": "REPLACE_WITH_ID_FROM_NEXT",
                    "student_answer": "B",
                    "time_taken_seconds": 20.0,
                }
            ]
        }
    )

    question_id: str = Field(
        default="REPLACE_WITH_ID_FROM_NEXT",
        examples=["REPLACE_WITH_ID_FROM_NEXT"],
    )
    student_answer: str = Field(default="B", examples=["B", "True", "False"])
    time_taken_seconds: float = Field(default=20.0, ge=0.0)


class CreateCustomizableQuizRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "student_id": "mock-student-class-a",
                    "grade": 6,
                    "chapters": ["G6_C8", "G6_C7"],
                    "num_questions": 2,
                    "question_types": ["MCQ", "TrueFalse"],
                }
            ]
        }
    )

    student_id: str = Field(default="mock-student-class-a", examples=["mock-student-class-a"])
    grade: int = Field(default=6, ge=6, le=9)
    chapters: list[str] = Field(
        default_factory=lambda: ["G6_C8", "G6_C7"],
        min_length=1,
        description="Canonical chapter_ids from data/chapter_ids_g6_g9.csv (e.g. G6_C8).",
        examples=[["G6_C8", "G6_C7"]],
    )
    num_questions: int = Field(default=2, ge=1, le=30)
    question_types: list[QuestionType] | None = Field(
        default_factory=lambda: [QuestionType.MCQ, QuestionType.TRUE_FALSE],
    )


class TriggerPostLessonRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "student_id": "mock-student-class-a",
                    "chapter_id": "G6_C8",
                    "grade": 6,
                },
                {
                    "student_id": "mock-student-class-a",
                    "grade": 6,
                },
            ]
        }
    )

    student_id: str = Field(default="mock-student-class-a", examples=["mock-student-class-a"])
    chapter_id: str | None = Field(
        default=None,
        examples=["G6_C8"],
        description=(
            "Canonical chapter_id (e.g. G7_C2). "
            "Omit to resolve from Component 1 GET /progress. "
            "G{grade}_C8 is treated as a client stub and live C1 still wins; "
            "other explicit chapters are trusted. "
            "Fallback G{g}_C8 only when C1 is unreachable/unmappable."
        ),
    )
    grade: int | None = Field(default=None, ge=6, le=9)


class PostLessonContextResponse(BaseModel):
    """Chapter context resolved before / during post-lesson start."""

    student_id: str
    chapter_id: str
    grade: int
    source: str
    lesson_id: str | None = None


class TerminateSessionRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "reason": "frustration_threshold",
                    "source": "component_3",
                }
            ]
        }
    )

    reason: str | None = "frustration_threshold"
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
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "topic_id": "G6_C7_MAG_POLES",
                    "skill": None,
                    "dok_level": 2,
                    "question_type": "MCQ",
                    "count": 1,
                }
            ]
        }
    )

    topic_id: str = Field(default="G6_C7_MAG_POLES", examples=["G6_C7_MAG_POLES"])
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
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "grade": 6,
                    "chapter_name": "Magnets",
                    "topic_id": "G6_C7_MAG_POLES",
                    "skill": "Magnetic poles",
                    "dok_level": 1,
                    "question_type": "TrueFalse",
                    "sub_concept": "Poles",
                    "payload": {
                        "type": "TrueFalse",
                        "question": "Unlike poles of a magnet attract each other.",
                        "correct_answer": "True",
                        "distractor_tag": "MISCONCEPTION",
                        "distractor_label": "Believes like poles attract",
                    },
                }
            ]
        }
    )

    grade: int = Field(default=6, ge=6, le=9)
    chapter_name: str = "Magnets"
    topic_id: str = Field(default="G6_C7_MAG_POLES")
    skill: str = "Magnetic poles"
    dok_level: int = Field(default=1, ge=1, le=4)
    question_type: QuestionType = QuestionType.TRUE_FALSE
    payload: QuestionPayload
    sub_concept: str = "Poles"


class RejectQuestionRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "reason": "POOR_PHRASING",
                    "notes": "Stem is ambiguous for Grade 6.",
                }
            ]
        }
    )

    reason: RejectionReason = RejectionReason.POOR_PHRASING
    notes: str | None = "Stem is ambiguous for Grade 6."
