"""Teacher question-bank endpoints. No auth in this research phase."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from iae.api.bootstrap import Container
from iae.api.schemas import (
    CreateTeacherQuestionRequest,
    ErrorDetail,
    GenerateQuestionsRequest,
    GenerateQuestionsResponse,
    TeacherQuestionListResponse,
    TeacherTopicItem,
    TeacherTopicsResponse,
)
from iae.application.question_generation import RateLimitExceeded
from iae.application.teacher import NoRagContextError, UnknownTopicError
from iae.core.curriculum import DEFAULT_GRADE
from iae.core.models import Question, QuestionStatus

router = APIRouter(prefix="/teacher", tags=["Teacher Hub"])


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


@router.get(
    "/topics",
    response_model=TeacherTopicsResponse,
    summary="List skill catalog topics",
    description=(
        "Returns Excel-derived Topic IDs for a grade (`topics.yaml`), including "
        "chapter title, skill text, domain, and concept code."
    ),
    responses={200: {"description": "Topic catalog for the grade."}},
)
def list_topics(
    grade: int = Query(
        default=DEFAULT_GRADE,
        ge=6,
        le=9,
        description="Curriculum grade year.",
        examples=[6],
    ),
    container: Container = Depends(get_container),
) -> TeacherTopicsResponse:
    """List Excel Topic IDs and skills for a grade."""
    topics = container.teacher_service.list_topics(grade)
    return TeacherTopicsResponse(
        grade=grade,
        topics=[
            TeacherTopicItem(
                grade=t.grade,
                topic_id=t.topic_id,
                chapter_title=t.chapter_title,
                skill=t.skill,
                chapter_number=t.chapter_number,
                domain=t.domain,
                concept_code=t.concept_code,
            )
            for t in topics
        ],
    )


@router.post(
    "/generate",
    response_model=GenerateQuestionsResponse,
    summary="Generate questions from RAG",
    description=(
        "Uses Chroma chunks tagged with the given Topic ID to generate new bank "
        "items via the LLM. Items are stored as `pending` until approved."
    ),
    responses={
        200: {"description": "Generated pending questions."},
        400: {"model": ErrorDetail, "description": "Unknown Topic ID."},
        409: {"model": ErrorDetail, "description": "No RAG context for this topic."},
        429: {"model": ErrorDetail, "description": "LLM provider rate limit."},
    },
)
def generate_questions(
    payload: GenerateQuestionsRequest,
    container: Container = Depends(get_container),
) -> GenerateQuestionsResponse:
    """Generate pending bank items from Chroma RAG for one Topic ID."""
    try:
        created = container.teacher_service.generate(
            topic_id=payload.topic_id,
            skill=payload.skill,
            dok_level=payload.dok_level,
            question_type=payload.question_type,
            count=payload.count,
        )
    except UnknownTopicError:
        raise HTTPException(status_code=400, detail=f"Unknown Topic ID: {payload.topic_id}") from None
    except NoRagContextError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    return GenerateQuestionsResponse(created=len(created), questions=created)


@router.get(
    "/questions",
    response_model=TeacherQuestionListResponse,
    summary="List bank questions",
    description="Filter the Postgres question bank by status, Topic ID, and/or grade.",
    responses={200: {"description": "Matching questions (newest first)."}},
)
def list_questions(
    status: QuestionStatus | None = Query(
        default=None,
        description="Filter by approval status.",
        examples=["pending"],
    ),
    topic_id: str | None = Query(
        default=None,
        description="Exact Topic ID filter.",
        examples=["G6_C7_MAG_POLES"],
    ),
    grade: int | None = Query(default=None, ge=6, le=9, description="Grade year filter."),
    limit: int = Query(default=100, ge=1, le=500, description="Max rows to return."),
    container: Container = Depends(get_container),
) -> TeacherQuestionListResponse:
    """List bank questions filtered by status, topic_id, and/or grade."""
    return TeacherQuestionListResponse(
        questions=container.teacher_service.list_questions(
            status=status,
            topic_id=topic_id,
            grade=grade,
            limit=limit,
        )
    )


@router.post(
    "/questions/{question_id}/approve",
    response_model=Question,
    summary="Approve a question",
    description="Sets status to `approved` so diagnostic/placement flows can serve it.",
    responses={
        200: {"description": "Updated question."},
        404: {"model": ErrorDetail, "description": "Question not found."},
    },
)
def approve_question(
    question_id: str,
    container: Container = Depends(get_container),
) -> Question:
    """Mark a bank item approved so students can be served it."""
    try:
        return container.teacher_service.set_status(question_id, QuestionStatus.APPROVED)
    except KeyError:
        raise HTTPException(status_code=404, detail="Question not found.") from None


@router.post(
    "/questions/{question_id}/reject",
    response_model=Question,
    summary="Reject a question",
    description="Sets status to `rejected`. Rejected items are not served to students.",
    responses={
        200: {"description": "Updated question."},
        404: {"model": ErrorDetail, "description": "Question not found."},
    },
)
def reject_question(
    question_id: str,
    container: Container = Depends(get_container),
) -> Question:
    """Mark a bank item rejected (not served to students)."""
    try:
        return container.teacher_service.set_status(question_id, QuestionStatus.REJECTED)
    except KeyError:
        raise HTTPException(status_code=404, detail="Question not found.") from None


@router.post(
    "/questions",
    response_model=Question,
    summary="Add a custom teacher question",
    description=(
        "Inserts a manually authored item linked to a known Topic ID. "
        "Stored as `pending` / origin `teacher` until approved."
    ),
    responses={
        200: {"description": "Created question."},
        400: {"model": ErrorDetail, "description": "Unknown Topic ID or invalid payload."},
    },
)
def add_custom_question(
    payload: CreateTeacherQuestionRequest,
    container: Container = Depends(get_container),
) -> Question:
    """Insert a teacher-authored pending bank item for a known Topic ID."""
    try:
        return container.teacher_service.add_custom(
            grade=payload.grade,
            chapter_name=payload.chapter_name,
            topic_id=payload.topic_id,
            skill=payload.skill,
            dok_level=payload.dok_level,
            question_type=payload.question_type,
            payload=payload.payload,
            sub_concept=payload.sub_concept,
        )
    except UnknownTopicError:
        raise HTTPException(status_code=400, detail=f"Unknown Topic ID: {payload.topic_id}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
