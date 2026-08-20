"""Teacher dashboard routes under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from iae.api.bootstrap import Container
from iae.api.deps import get_container
from iae.api.schemas import (
    CreateTeacherQuestionRequest,
    ErrorDetail,
    GenerateQuestionsRequest,
    GenerateQuestionsResponse,
    RejectQuestionRequest,
    TeacherQuestionListResponse,
    TeacherTopicItem,
    TeacherTopicsResponse,
)
from iae.application.question_generation import RateLimitExceeded
from iae.application.teacher import NoRagContextError, UnknownTopicError
from iae.core.curriculum import DEFAULT_GRADE
from iae.core.models import Question, QuestionStatus, QuestionType

router = APIRouter(prefix="/api/v1/teacher", tags=["Teacher Hub"])


@router.get(
    "/topics",
    response_model=TeacherTopicsResponse,
    summary="List skill catalog topics",
)
def list_topics(
    grade: int = Query(default=DEFAULT_GRADE, ge=6, le=9),
    container: Container = Depends(get_container),
) -> TeacherTopicsResponse:
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
)
def generate_questions(
    payload: GenerateQuestionsRequest,
    container: Container = Depends(get_container),
) -> GenerateQuestionsResponse:
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
    summary="List bank questions (class / DOK / type filters)",
)
def list_questions(
    status: QuestionStatus | None = Query(default=None),
    topic_id: str | None = Query(default=None),
    grade: int | None = Query(default=None, ge=6, le=9),
    class_code: str | None = Query(default=None, description="Filter to grades of students in this class."),
    dok_level: int | None = Query(default=None, ge=1, le=4),
    question_type: QuestionType | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    container: Container = Depends(get_container),
) -> TeacherQuestionListResponse:
    return TeacherQuestionListResponse(
        questions=container.teacher_service.list_questions(
            status=status,
            topic_id=topic_id,
            grade=grade,
            class_code=class_code,
            dok_level=dok_level,
            question_type=question_type,
            limit=limit,
        )
    )


@router.post(
    "/questions/{question_id}/approve",
    response_model=Question,
    summary="Approve a question",
)
def approve_question(
    question_id: str,
    container: Container = Depends(get_container),
) -> Question:
    try:
        return container.teacher_service.set_status(question_id, QuestionStatus.APPROVED)
    except KeyError:
        raise HTTPException(status_code=404, detail="Question not found.") from None


@router.post(
    "/questions/{question_id}/reject",
    response_model=Question,
    summary="Reject with reason",
    description=(
        "Rejection reasons: `FACTUAL_ERROR` | `OUT_OF_SCOPE` | `POOR_PHRASING` | "
        "`TOO_EASY` | `TOO_HARD` | `OTHER`. "
        "On `FACTUAL_ERROR`, an LLM check may set `rejection_confirmed_ai=true`."
    ),
    responses={404: {"model": ErrorDetail}},
)
def reject_question(
    question_id: str,
    payload: RejectQuestionRequest,
    container: Container = Depends(get_container),
) -> Question:
    try:
        return container.teacher_service.reject(
            question_id,
            reason=payload.reason,
            notes=payload.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Question not found.") from None


@router.post(
    "/questions",
    response_model=Question,
    summary="Add a custom teacher question",
)
def add_custom_question(
    payload: CreateTeacherQuestionRequest,
    container: Container = Depends(get_container),
) -> Question:
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
