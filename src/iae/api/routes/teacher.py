"""Teacher question-bank endpoints. No auth in this research phase."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from iae.api.bootstrap import Container
from iae.api.schemas import (
    CreateTeacherQuestionRequest,
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

router = APIRouter(prefix="/teacher", tags=["teacher"])


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


@router.get("/topics", response_model=TeacherTopicsResponse)
def list_topics(
    grade: int = DEFAULT_GRADE,
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


@router.post("/generate", response_model=GenerateQuestionsResponse)
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


@router.get("/questions", response_model=TeacherQuestionListResponse)
def list_questions(
    status: QuestionStatus | None = Query(default=None),
    topic_id: str | None = Query(default=None),
    grade: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    container: Container = Depends(get_container),
) -> TeacherQuestionListResponse:
    return TeacherQuestionListResponse(
        questions=container.teacher_service.list_questions(
            status=status,
            topic_id=topic_id,
            grade=grade,
            limit=limit,
        )
    )


@router.post("/questions/{question_id}/approve", response_model=Question)
def approve_question(
    question_id: str,
    container: Container = Depends(get_container),
) -> Question:
    try:
        return container.teacher_service.set_status(question_id, QuestionStatus.APPROVED)
    except KeyError:
        raise HTTPException(status_code=404, detail="Question not found.") from None


@router.post("/questions/{question_id}/reject", response_model=Question)
def reject_question(
    question_id: str,
    container: Container = Depends(get_container),
) -> Question:
    try:
        return container.teacher_service.set_status(question_id, QuestionStatus.REJECTED)
    except KeyError:
        raise HTTPException(status_code=404, detail="Question not found.") from None


@router.post("/questions", response_model=Question)
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
