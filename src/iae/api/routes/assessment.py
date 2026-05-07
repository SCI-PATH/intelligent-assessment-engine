"""Diagnostic assessment endpoints.

The router is thin: each handler translates the HTTP request into an
application-service call and re-shapes the result for the client. All
session state lives on the server so the Streamlit (or any other) frontend
stays stateless.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from iae.api.bootstrap import Container
from iae.api.schemas import (
    ChaptersResponse,
    CreateSessionRequest,
    NextQuestionResponse,
    ResultsResponse,
    SessionResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    TelemetryPayload,
)
from iae.application.sessions import NoQuestionAvailable
from iae.core.curriculum import get_chapter_names
from iae.core.settings import get_config

router = APIRouter(prefix="/assessment", tags=["assessment"])


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


@router.get("/chapters", response_model=ChaptersResponse)
def list_chapters() -> ChaptersResponse:
    return ChaptersResponse(
        chapters=get_chapter_names(),
        max_questions=get_config().max_questions,
    )


@router.post("/sessions", response_model=SessionResponse)
def create_session(
    payload: CreateSessionRequest,
    container: Container = Depends(get_container),
) -> SessionResponse:
    if payload.chapter_name not in get_chapter_names():
        raise HTTPException(status_code=400, detail="Unknown chapter.")
    session = container.session_service.create_session(payload.chapter_name)
    return SessionResponse(
        session_id=session.session_id,
        scope_chapter=session.scope_chapter,
        questions_asked=session.questions_asked,
        max_questions=get_config().max_questions,
    )


@router.post("/sessions/{session_id}/next", response_model=NextQuestionResponse)
def next_question(
    session_id: str,
    container: Container = Depends(get_container),
) -> NextQuestionResponse:
    try:
        outcome = container.session_service.next_question(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found.") from None
    except NoQuestionAvailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    session = container.session_service.get_session(session_id)
    return NextQuestionResponse(
        question=outcome.question,
        telemetry=TelemetryPayload(
            state=outcome.state,
            action=outcome.action,
            rolling_accuracy=outcome.rolling_accuracy,
            questions_asked=session.questions_asked,
        ),
    )


@router.post("/sessions/{session_id}/answer", response_model=SubmitAnswerResponse)
def submit_answer(
    session_id: str,
    payload: SubmitAnswerRequest,
    container: Container = Depends(get_container),
) -> SubmitAnswerResponse:
    try:
        result, session = container.session_service.submit_answer(
            session_id=session_id,
            question_id=payload.question_id,
            student_answer=payload.student_answer,
            time_taken_seconds=payload.time_taken_seconds,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {exc}") from None

    max_questions = get_config().max_questions
    return SubmitAnswerResponse(
        grade=result,
        questions_asked=session.questions_asked,
        is_complete=session.questions_asked >= max_questions,
    )


@router.get("/sessions/{session_id}/results", response_model=ResultsResponse)
def session_results(
    session_id: str,
    container: Container = Depends(get_container),
) -> ResultsResponse:
    try:
        session = container.session_service.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found.") from None
    correct = sum(1 for a in session.history if a.is_correct)
    total = len(session.history)
    return ResultsResponse(
        scope_chapter=session.scope_chapter,
        questions_asked=session.questions_asked,
        correct_count=correct,
        raw_accuracy=correct / total if total else 0.0,
        history=session.history,
    )
