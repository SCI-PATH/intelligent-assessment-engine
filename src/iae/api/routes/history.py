"""Student history and Component 1 initial-category under /api/v1/assessment-engine."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from iae.api.bootstrap import Container
from iae.api.deps import get_container
from iae.api.integration_ids import resolve_student_id
from iae.domain.models import SessionState
from iae.api.schemas import (
    AmplitudeCategoryResponse,
    ErrorDetail,
    QuizSessionResponse,
)

router = APIRouter(
    prefix="/api/v1/assessment-engine/students",
    tags=["Student History"],
)


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
    summary="Get student initial Aptitude category",
    description=(
        "**Purpose:** Read persisted Aptitude category after evaluate.\n\n"
        "**Caller:** Component 1 (Lesson Engine) and Frontend.\n\n"
        "**Path:** `student_id` — local testing: `mock-student-class-a`.\n\n"
        "**How to Test:** Run Aptitude evaluate first → Execute with the same student id."
    ),
    responses={404: {"model": ErrorDetail}},
    tags=["Aptitude Diagnostic Test"],
)
def initial_category(
    student_id: str = Path(..., examples=["mock-student-class-a"]),
    container: Container = Depends(get_container),
) -> AmplitudeCategoryResponse:
    sid = resolve_student_id(student_id)
    profile = container.amplitude_service.initial_category(sid)
    if profile is None:
        raise HTTPException(status_code=404, detail="Student not found.")
    return AmplitudeCategoryResponse(
        student_id=sid,
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
    description=(
        "**Purpose:** List recent quiz sessions for a student (newest first).\n\n"
        "**Caller:** Frontend.\n\n"
        "**Query:** `limit` (1–200, default 50)."
    ),
)
def list_sessions(
    student_id: str = Path(..., examples=["mock-student-class-a"]),
    limit: int = Query(default=50, ge=1, le=200),
    container: Container = Depends(get_container),
) -> list[QuizSessionResponse]:
    sid = resolve_student_id(student_id)
    return [_session_summary(s) for s in container.history_service.list_sessions(sid, limit=limit)]


@router.get(
    "/{student_id}/sessions/{session_id}",
    summary="Session detail with expected answers",
    description=(
        "**Purpose:** Full attempt list with student answers and expected answers from bank.\n\n"
        "**Caller:** Frontend."
    ),
    responses={404: {"model": ErrorDetail}},
)
def session_detail(
    student_id: str = Path(..., examples=["mock-student-class-a"]),
    session_id: str = Path(
        ...,
        description="Paste session_id from create quiz or list sessions.",
        examples=["REPLACE_WITH_SESSION_ID"],
    ),
    container: Container = Depends(get_container),
) -> dict:
    sid = resolve_student_id(student_id)
    try:
        return container.history_service.get_session_detail(sid, session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found.") from None


@router.post(
    "/{student_id}/sessions/{session_id}/analyze",
    summary="LLM constructive analysis for wrong items",
    description=(
        "**Purpose:** Constructive LLM analysis of incorrect attempts; stores `ai_analysis`.\n\n"
        "**Caller:** Frontend."
    ),
    responses={404: {"model": ErrorDetail}},
)
def analyze_session(
    student_id: str = Path(..., examples=["mock-student-class-a"]),
    session_id: str = Path(
        ...,
        description="Paste session_id that has at least one wrong answer.",
        examples=["REPLACE_WITH_SESSION_ID"],
    ),
    container: Container = Depends(get_container),
) -> dict:
    sid = resolve_student_id(student_id)
    try:
        return container.history_service.analyze_session(sid, session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found.") from None
