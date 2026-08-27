"""Quizzes and testing loops under /api/v1/assessment-engine."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from iae.api.bootstrap import Container
from iae.api.deps import get_container
from iae.api.integration_ids import resolve_grade, resolve_student_id, resolve_terminate_actor
from iae.api.schemas import (
    CreateCustomizableQuizRequest,
    ErrorDetail,
    PostLessonContextResponse,
    QuizAnswerResponse,
    QuizNextResponse,
    QuizSessionResponse,
    SubmitAnswerRequest,
    TerminateSessionRequest,
    TriggerPostLessonRequest,
)
from iae.domain.exceptions import NoQuestionAvailable
from iae.domain.models import SessionState

router = APIRouter(
    prefix="/api/v1/assessment-engine/quizzes",
    tags=["Quizzes and Testing Loops"],
)


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
    "/customizable",
    response_model=QuizSessionResponse,
    summary="Create customizable quiz session",
    description=(
        "**Purpose:** Start a Time-Discounted Elo DDA session for selected chapters.\n\n"
        "**Caller:** Frontend.\n\n"
        "**Outbound Component 4:** `POST {COMPONENT_4_URL}/api/v1/quiz/bkt-snapshot` "
        "with `{ user_id, chapter_ids }` (cached in session memory; mock if URL empty).\n\n"
        "**Request body:**\n"
        "```json\n"
        "{\n"
        '  "student_id": "mock-student-class-a",\n'
        '  "grade": 6,\n'
        '  "chapters": ["G6_C7"],\n'
        '  "num_questions": 3,\n'
        '  "question_types": ["MCQ", "TrueFalse"]\n'
        "}\n"
        "```\n"
        "`chapters` = canonical ids from `data/chapter_ids_g6_g9.csv`.\n\n"
        "**How to Test:** Execute → copy `session_id` → call `/next`."
    ),
)
def create_customizable(
    payload: CreateCustomizableQuizRequest,
    container: Container = Depends(get_container),
) -> QuizSessionResponse:
    student_id = resolve_student_id(payload.student_id)
    grade = resolve_grade(payload.grade)
    try:
        session = container.quiz_service.create_customizable(
            user_id=student_id,
            grade=grade,
            chapters=payload.chapters,
            num_questions=payload.num_questions,
            question_types=payload.question_types,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _session_response(session)


@router.get(
    "/post-lesson/context",
    response_model=PostLessonContextResponse,
    summary="Resolve chapter for post-lesson (from C1 when omitted)",
    description=(
        "**Purpose:** Ask Component 1 which `chapter_id` to use before starting "
        "a post-lesson quiz (or preview what C2 would resolve).\n\n"
        "**Resolution rule:**\n"
        "- Omit `chapter_id` → always call Component 1 "
        "`GET {COMPONENT_1_URL}/progress?user_id=` "
        "(maps `g7_sci_02` → `G7_C2`).\n"
        "- Body `G{grade}_C8` is treated as a **client stub** (Game fallback) — "
        "C2 still prefers live C1 over that stub.\n"
        "- Any other explicit chapter (e.g. `G7_C3`) is trusted as `source=request`.\n"
        "- `source=fallback` / grade-aware `G{g}_C8` only when C1 is off, times out, "
        "or cannot map (`C1_HTTP_LIVE`).\n\n"
        "**Caller:** Frontend. Prefer this when the FE does not already know the lesson chapter.\n\n"
        "Then call `POST /quizzes/post-lesson` with the returned `chapter_id` "
        "(or omit `chapter_id` and let POST resolve C1 again)."
    ),
    responses={400: {"model": ErrorDetail}},
)
def post_lesson_context(
    student_id: str | None = Query(default=None, examples=["mock-student-class-a"]),
    grade: int | None = Query(default=None, ge=6, le=9),
    container: Container = Depends(get_container),
) -> PostLessonContextResponse:
    sid = resolve_student_id(student_id)
    try:
        resolved = container.quiz_service.resolve_post_lesson_chapter(
            student_id=sid,
            chapter_id=None,
            grade=grade,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PostLessonContextResponse(**resolved)


@router.post(
    "/post-lesson",
    response_model=QuizSessionResponse,
    summary="Start post-lesson quiz (Component 1 / Component 3)",
    description=(
        "**Purpose:** Open a 15-question chapter quiz after a lesson completes.\n\n"
        "**Caller:** Frontend, Component 1, or Component 3.\n\n"
        "**Chapter resolution:**\n"
        "- Omit `chapter_id` → Component 1 `/progress` (live → `source=component_1`).\n"
        "- `G{grade}_C8` in the body is a known Game/FE stub → still prefer live C1.\n"
        "- Other explicit chapters (e.g. `G7_C2`) win as `source=request`.\n"
        "- C1 down / unmappable → grade-aware `G{g}_C8` with `source=fallback` only.\n\n"
        "**Outbound:** C4 BKT snapshot at start; C1 quiz-ready notify after session create "
        "(soft-fail if C1 has no quiz-ready route).\n\n"
        "**Request body:**\n"
        "```json\n"
        "{\n"
        '  "student_id": "mock-student-class-a",\n'
        '  "chapter_id": "G6_C7",\n'
        '  "grade": 6\n'
        "}\n"
        "```\n"
        "`chapter_id` may be omitted to resolve from C1.\n\n"
        "**How to Test:** Execute → use `session_id` with `/next` + `/answer`."
    ),
)
def trigger_post_lesson(
    payload: TriggerPostLessonRequest,
    container: Container = Depends(get_container),
) -> QuizSessionResponse:
    student_id = resolve_student_id(payload.student_id)
    # --- LIVE INTEGRATION (uncomment tomorrow): pass C1 student_id through unchanged ---
    # student_id = (payload.student_id or "").strip() or student_id
    grade = resolve_grade(payload.grade) if payload.grade is not None else None

    try:
        session = container.quiz_service.trigger_post_lesson(
            student_id=student_id,
            chapter_id=payload.chapter_id,
            grade=grade if grade is not None else payload.grade,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _session_response(session)


@router.get(
    "/{session_id}/next",
    response_model=QuizNextResponse,
    summary="Next DDA question",
    description=(
        "**Purpose:** Serve the next approved bank item (Elo → target DOK).\n\n"
        "**Caller:** Frontend.\n\n"
        "**How to Test:** Paste `session_id` → copy `question.id` for `/answer`. "
        "409 when session complete or bank exhausted after rotation."
    ),
    responses={
        404: {"model": ErrorDetail},
        409: {"model": ErrorDetail, "description": "No question available / session ended."},
    },
)
def next_question(
    session_id: str = Path(
        ...,
        description="Paste session_id from customizable or post-lesson create.",
        examples=["REPLACE_WITH_SESSION_ID"],
    ),
    container: Container = Depends(get_container),
) -> QuizNextResponse:
    try:
        question, decision = container.quiz_service.next_question(session_id)
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
        target_dok=decision.dok_level,
        target_topic_id=decision.topic_id or None,
        target_question_type=decision.question_type.value,
    )


@router.post(
    "/{session_id}/answer",
    response_model=QuizAnswerResponse,
    summary="Submit quiz answer",
    description=(
        "**Purpose:** Grade one answer, update Elo, persist attempt, notify Component 4.\n\n"
        "**Caller:** Frontend.\n\n"
        "**Outbound Component 4:** `POST {COMPONENT_4_URL}/api/v1/assessment-submit` "
        "with the unified analytics payload (all keys; unused fields are `null`).\n\n"
        "**Request body:**\n"
        "```json\n"
        "{\n"
        '  "question_id": "<uuid from /next>",\n'
        '  "student_answer": "B",\n'
        '  "time_taken_seconds": 20.0\n'
        "}\n"
        "```\n\n"
        "**How to Test:** Use `question_id` from `/next` → repeat until complete or terminate."
    ),
)
def submit_answer(
    payload: SubmitAnswerRequest,
    session_id: str = Path(
        ...,
        description="Same session_id used for /next.",
        examples=["REPLACE_WITH_SESSION_ID"],
    ),
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
    "/{session_id}/results",
    summary="Quiz session results",
    description=(
        "**Purpose:** Summary of a quiz session (accuracy, history, optional ai_analysis).\n\n"
        "**Caller:** Frontend.\n\n"
        "**How to Test:** After answering (or terminating), Execute with the same `session_id`."
    ),
    responses={404: {"model": ErrorDetail}},
)
def quiz_results(
    session_id: str = Path(
        ...,
        examples=["REPLACE_WITH_SESSION_ID"],
    ),
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
    "/{session_id}/terminate",
    response_model=QuizSessionResponse,
    summary="Kill-switch terminate (Component 3)",
    description=(
        "**Purpose:** End an active quiz when the learner runs out of lives or hits a failure limit.\n\n"
        "**Caller:** Component 3. Idempotent if already ended.\n\n"
        "**Request body:**\n"
        "```json\n"
        "{\n"
        '  "reason": "frustration_threshold",\n'
        '  "source": "component_3"\n'
        "}\n"
        "```\n\n"
        "**How to Test:** Start any quiz → terminate → `/next` should 409."
    ),
    responses={404: {"model": ErrorDetail}},
)
def terminate_session(
    payload: TerminateSessionRequest,
    session_id: str = Path(
        ...,
        examples=["REPLACE_WITH_SESSION_ID"],
    ),
    container: Container = Depends(get_container),
) -> QuizSessionResponse:
    actor = resolve_terminate_actor(payload.source)
    # --- LIVE INTEGRATION (uncomment tomorrow): trust C3 source/reason as sent ---
    # actor = (payload.source or "component_3").strip()
    # reason = (payload.reason or f"{actor}_kill_switch").strip()

    reason = payload.reason or f"{actor}_kill_switch"
    try:
        session = container.quiz_service.terminate(session_id, reason=reason)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found.") from None
    return _session_response(session)
