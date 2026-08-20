"""Student history dashboard under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from iae.api.bootstrap import Container
from iae.api.deps import get_container
from iae.api.schemas import AmplitudeCategoryResponse, ErrorDetail, QuizSessionResponse
from iae.core.models import SessionState

router = APIRouter(prefix="/api/v1/student", tags=["Student History"])


def _session_summary(session: SessionState) -> QuizSessionResponse:
    return QuizSessionResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        scope_chapter=session.scope_chapter,
        scope_chapters=list(session.scope_chapters),
        session_kind=session.session_kind.value,
        status=session.status.value,
        questions_asked=session.questions_asked,
        max_questions=session.max_questions,
        elo_rating=session.elo_rating,
    )


@router.get(
    "/{student_id}/initial-category",
    response_model=AmplitudeCategoryResponse,
    summary="Get student initial Amplitude category",
    responses={404: {"model": ErrorDetail}},
)
def initial_category(
    student_id: str,
    container: Container = Depends(get_container),
) -> AmplitudeCategoryResponse:
    profile = container.amplitude_service.initial_category(student_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Student not found.")
    return AmplitudeCategoryResponse(
        student_id=student_id,
        initial_category=profile.initial_category.value if profile.initial_category else None,
        initial_category_score=profile.initial_category_score,
        placement_category=(
            profile.placement_category.value if profile.placement_category else None
        ),
    )


@router.get(
    "/{student_id}/sessions",
    response_model=list[QuizSessionResponse],
    summary="List student quiz sessions",
)
def list_sessions(
    student_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    container: Container = Depends(get_container),
) -> list[QuizSessionResponse]:
    return [_session_summary(s) for s in container.history_service.list_sessions(student_id, limit=limit)]


@router.get(
    "/{student_id}/sessions/{session_id}",
    summary="Session detail with expected answers",
    responses={404: {"model": ErrorDetail}},
)
def session_detail(
    student_id: str,
    session_id: str,
    container: Container = Depends(get_container),
) -> dict:
    try:
        return container.history_service.get_session_detail(student_id, session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found.") from None


@router.post(
    "/{student_id}/sessions/{session_id}/analyze",
    summary="LLM constructive analysis for wrong items",
    responses={404: {"model": ErrorDetail}},
)
def analyze_session(
    student_id: str,
    session_id: str,
    container: Container = Depends(get_container),
) -> dict:
    try:
        return container.history_service.analyze_session(student_id, session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found.") from None
