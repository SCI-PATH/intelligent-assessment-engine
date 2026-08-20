"""Customizable quiz + post-lesson + kill-switch under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from iae.api.bootstrap import Container
from iae.api.deps import get_container
from iae.api.schemas import (
    CreateCustomizableQuizRequest,
    ErrorDetail,
    QuizAnswerResponse,
    QuizNextResponse,
    QuizSessionResponse,
    SubmitAnswerRequest,
    TerminateSessionRequest,
    TriggerPostLessonRequest,
)
from iae.application.sessions import NoQuestionAvailable
from iae.core.models import SessionState
from iae.dda_algorithms import elo_to_target_dok

router = APIRouter(tags=["Quizzes"])


def _session_response(session: SessionState) -> QuizSessionResponse:
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


@router.post(
    "/api/v1/quizzes/customizable",
    response_model=QuizSessionResponse,
    summary="Create customizable quiz session",
    description=(
        "Starts a Time-Discounted Elo DDA session. "
        "`chapters` must be canonical Component 4 chapter_ids (`G6_C8`, …) "
        "from `data/chapter_ids_g6_g9.csv` (titles are normalized). "
        "At start, Component 2 calls C4 `POST /api/v1/quiz/bkt-snapshot` "
        "and keeps `topic_bkt` in **session memory only** (mock fallback if C4 is down)."
    ),
)
def create_customizable(
    payload: CreateCustomizableQuizRequest,
    container: Container = Depends(get_container),
) -> QuizSessionResponse:
    try:
        session = container.quiz_service.create_customizable(
            user_id=payload.student_id,
            grade=payload.grade,
            chapters=payload.chapters,
            num_questions=payload.num_questions,
            question_types=payload.question_types,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _session_response(session)


@router.get(
    "/api/v1/quizzes/{session_id}/next",
    response_model=QuizNextResponse,
    summary="Next DDA question",
    responses={
        404: {"model": ErrorDetail},
        409: {"model": ErrorDetail, "description": "No question available / session ended."},
    },
)
def next_question(
    session_id: str,
    container: Container = Depends(get_container),
) -> QuizNextResponse:
    try:
        question = container.quiz_service.next_question(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found.") from None
    except NoQuestionAvailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    session = container.quiz_service.get(session_id)
    elo = session.elo_rating if session else 1000.0
    return QuizNextResponse(
        question=question,
        elo_rating=elo,
        questions_asked=session.questions_asked if session else 0,
        max_questions=session.max_questions if session else 0,
        target_dok=elo_to_target_dok(elo),
    )


@router.post(
    "/api/v1/quizzes/{session_id}/answer",
    response_model=QuizAnswerResponse,
    summary="Submit quiz answer",
    description=(
        "Grades the item, updates Elo, persists the attempt, and POSTs the unified "
        "Component 4 payload to `POST /api/v1/assessment-submit` "
        "(includes optional `chapter_ids` for multi-chapter sessions). "
        "Session-memory `topic_bkt` is refreshed from the C4 response when present."
    ),
)
def submit_answer(
    session_id: str,
    payload: SubmitAnswerRequest,
    container: Container = Depends(get_container),
) -> QuizAnswerResponse:
    try:
        result, session, elo = container.quiz_service.submit_answer(
            session_id=session_id,
            question_id=payload.question_id,
            student_answer=payload.student_answer,
            time_taken_seconds=payload.time_taken_seconds,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return QuizAnswerResponse(
        grade=result,
        questions_asked=session.questions_asked,
        is_complete=session.status.value != "active",
        elo_rating=elo.new_rating,
        next_dok=elo.next_dok,
        status=session.status.value,
    )


@router.get(
    "/api/v1/quizzes/{session_id}/results",
    summary="Quiz session results",
    responses={404: {"model": ErrorDetail}},
)
def quiz_results(
    session_id: str,
    container: Container = Depends(get_container),
) -> dict:
    session = container.quiz_service.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    correct = sum(1 for item in session.history if item.is_correct)
    asked = len(session.history)
    return {
        "session_id": session.session_id,
        "status": session.status.value,
        "session_kind": session.session_kind.value,
        "scope_chapter": session.scope_chapter,
        "questions_asked": session.questions_asked,
        "correct_count": correct,
        "raw_accuracy": (correct / asked) if asked else 0.0,
        "elo_rating": session.elo_rating,
        "history": session.history,
        "ai_analysis": session.ai_analysis,
    }


@router.post(
    "/api/v1/quiz/trigger-post-lesson",
    response_model=QuizSessionResponse,
    summary="Trigger post-lesson quiz (Component 1 inbound)",
    description=(
        "Creates a chapter-scoped DDA session capped at 15 questions. "
        "`chapter_id` must be a canonical id like `G6_C8`."
    ),
)
def trigger_post_lesson(
    payload: TriggerPostLessonRequest,
    container: Container = Depends(get_container),
) -> QuizSessionResponse:
    session = container.quiz_service.trigger_post_lesson(
        student_id=payload.student_id,
        chapter_id=payload.chapter_id,
        grade=payload.grade,
    )
    return _session_response(session)


@router.post(
    "/api/v1/quiz/{session_id}/terminate",
    response_model=QuizSessionResponse,
    summary="Kill-switch terminate (Component 3 inbound)",
    description="Marks the session terminated. Idempotent if already ended.",
    responses={404: {"model": ErrorDetail}},
)
def terminate_session(
    session_id: str,
    payload: TerminateSessionRequest,
    container: Container = Depends(get_container),
) -> QuizSessionResponse:
    reason = payload.reason or f"{payload.source}_kill_switch"
    try:
        session = container.quiz_service.terminate(session_id, reason=reason)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found.") from None
    return _session_response(session)
