"""Diagnostic assessment endpoints.

The router is thin: each handler translates the HTTP request into an
application-service call and re-shapes the result for the client. All
session state lives on the server so the Streamlit (or any other) frontend
stays stateless.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from iae.api.bootstrap import Container
from iae.api.schemas import (
    ActionTelemetry,
    ChaptersResponse,
    CreateSessionRequest,
    ErrorDetail,
    NextQuestionResponse,
    ResultsResponse,
    SessionResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    TelemetryPayload,
)
from iae.application.sessions import NoQuestionAvailable
from iae.core.curriculum import (
    DEFAULT_GRADE,
    UnknownGradeError,
    get_available_grades,
    get_chapter_names,
)
from iae.core.settings import get_config

router = APIRouter(prefix="/assessment", tags=["Diagnostic Assessment"])


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


@router.get(
    "/chapters",
    response_model=ChaptersResponse,
    summary="List curriculum chapters",
    description=(
        "Returns chapter titles for a grade year plus the configured "
        "`max_questions` for diagnostic sessions."
    ),
    responses={
        200: {"description": "Chapter list for the requested grade."},
        400: {"model": ErrorDetail, "description": "Unknown or unsupported grade."},
    },
)
def list_chapters(
    grade: int = Query(
        default=DEFAULT_GRADE,
        ge=6,
        le=9,
        description="Curriculum grade year.",
        examples=[6],
    ),
) -> ChaptersResponse:
    """List curriculum chapter titles and session max_questions for a grade."""
    try:
        chapters = get_chapter_names(grade)
    except UnknownGradeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChaptersResponse(
        grade=grade,
        chapters=chapters,
        max_questions=get_config().max_questions,
    )


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=200,
    summary="Create diagnostic session",
    description=(
        "Opens a new adaptive diagnostic session scoped to one chapter. "
        "Persist `session_id` on the client for subsequent `/next` and `/answer` calls."
    ),
    responses={
        200: {"description": "Session created."},
        400: {"model": ErrorDetail, "description": "Unknown grade or chapter name."},
    },
)
def create_session(
    payload: CreateSessionRequest,
    container: Container = Depends(get_container),
) -> SessionResponse:
    """Create a chapter-scoped adaptive diagnostic session."""
    try:
        chapter_names = get_chapter_names(payload.grade)
    except UnknownGradeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.chapter_name not in chapter_names:
        available = get_available_grades()
        raise HTTPException(
            status_code=400,
            detail=f"Unknown chapter for grade {payload.grade}. Available grades: {available}.",
        )
    session = container.session_service.create_session(
        payload.chapter_name,
        user_id=payload.user_id,
        grade=payload.grade,
    )
    return SessionResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        scope_chapter=session.scope_chapter,
        questions_asked=session.questions_asked,
        max_questions=get_config().max_questions,
    )


@router.post(
    "/sessions/{session_id}/next",
    response_model=NextQuestionResponse,
    summary="Get next adaptive question",
    description=(
        "Serves the next bank question for the session using the adaptive policy. "
        "The returned `question.payload` includes answer keys — strip them before "
        "showing the item to a student."
    ),
    responses={
        200: {"description": "Next question and adaptive telemetry."},
        404: {"model": ErrorDetail, "description": "Session not found."},
        409: {
            "model": ErrorDetail,
            "description": "No eligible approved question left for this session.",
        },
    },
)
def next_question(
    session_id: str,
    container: Container = Depends(get_container),
) -> NextQuestionResponse:
    """Serve the next adaptive bank question (includes answer keys — strip for UI)."""
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
            action=ActionTelemetry(
                target_chapter=outcome.action.target_chapter,
                next_difficulty_level=outcome.action.next_difficulty_level,
                next_question_type=outcome.action.next_question_type,
                next_sub_concept=outcome.action.next_sub_concept,
                rule_triggered=outcome.action.rule_triggered,
                dok_reason=outcome.action.dok_reason,
                question_type_reason=outcome.action.question_type_reason,
                dok_summary=outcome.action.dok_summary,
                type_summary=outcome.action.type_summary,
                dok_trace=outcome.action.dok_trace,
                type_trace=outcome.action.type_trace,
                estimated_theta=outcome.action.estimated_theta,
                item_b=outcome.action.item_b,
                previous_response_time_seconds=outcome.action.previous_response_time_seconds,
                rapid_guessing_detected=outcome.action.rapid_guessing_detected,
                format_simplification_triggered=outcome.action.format_simplification_triggered,
            ),
            rolling_accuracy=outcome.rolling_accuracy,
            questions_asked=session.questions_asked,
        ),
    )


@router.post(
    "/sessions/{session_id}/answer",
    response_model=SubmitAnswerResponse,
    summary="Submit answer and emit Component 4 analytics",
    description=(
            "**Component 4 / BKT Analytics contract.** Grades the student's answer, "
            "persists `question_engine.attempts`, and writes `question_engine.analytics_events` "
            "with a **unified JSON payload** (same keys for every question type; "
            "non-applicable fields are explicitly `null`):\n"
            "- always: `user_id`, `topic_id`, `question_id`, `question_type`, `is_correct`, "
            "`response_time_s`, `difficulty_level`, `subtopic_id`, `source`\n"
            "- `similarity_score` — ShortAnswer / MultiBlank only\n"
            "- `distractor_tag` / `distractor_label` / `chosen_distractor_text` — wrong MCQ "
            "or wrong TrueFalse "
            "(`NEAR_MISS` | `MISCONCEPTION` | `COMPLETE_MISS`)\n"
            "- `error_category` — ShortAnswer / MultiBlank\n"
            "- `detailed_explanation` — ShortAnswer / TrueFalse\n"
            "- `missed_blanks` — MultiBlank JSON object\n\n"
            "Also returns type-specific diagnostic fields on `grade` and whether the "
            "session is complete (`is_complete`). See `COMPONENT2_COMPONENT4_INTEGRATION.md`."
        ),
        responses={
            200: {
                "description": (
                    "Graded attempt. Unified analytics event persisted for Component 4 "
                    "for all four question types."
                )
            },
            404: {"model": ErrorDetail, "description": "Session or question not found."},
        },
    )
def submit_answer(
    session_id: str,
    payload: SubmitAnswerRequest,
    container: Container = Depends(get_container),
) -> SubmitAnswerResponse:
    """Grade one answer and persist the Component 4 unified analytics payload."""
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


@router.get(
    "/sessions/{session_id}/results",
    response_model=ResultsResponse,
    summary="Get session results",
    description="Returns aggregate accuracy and the full attempt history for a session.",
    responses={
        200: {"description": "Session summary."},
        404: {"model": ErrorDetail, "description": "Session not found."},
    },
)
def session_results(
    session_id: str,
    container: Container = Depends(get_container),
) -> ResultsResponse:
    """Return aggregate accuracy and full attempt history for a session."""
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
