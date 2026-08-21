"""Amplitude Diagnostic Test routes under /api/v1/assessment-engine."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from iae.api.bootstrap import Container
from iae.api.deps import get_container
from iae.api.integration_ids import resolve_grade, resolve_student_id
from iae.domain.curriculum import DEFAULT_GRADE
from iae.domain.models import AmplitudeEvaluation, Question, StudentProfile
from iae.api.schemas import (
    AmplitudeEvaluateRequest,
    AmplitudeSurveyRequest,
    ErrorDetail,
    PlacementQuizItem,
    PlacementQuizResponse,
)
from iae.application.amplitude_service import AmplitudeQuizUnavailable

router = APIRouter(
    prefix="/api/v1/assessment-engine/amplitude",
    tags=["Amplitude Diagnostic Test"],
)


def _public_prompt(question: Question) -> dict:
    payload = question.payload.model_dump(mode="json")
    for secret in (
        "correct_answer",
        "ideal_answer",
        "answers",
        "keywords",
        "option_diagnostics",
        "distractor_tag",
        "distractor_label",
    ):
        payload.pop(secret, None)
    return payload


def _quiz_item(question: Question) -> PlacementQuizItem:
    return PlacementQuizItem(
        id=question.id,
        chapter_name=question.chapter_name,
        topic_id=question.topic_id,
        skill=question.skill,
        dok_level=question.dok_level,
        question_type=question.question_type,
        grade=question.grade,
        prompt=_public_prompt(question),
    )


@router.post(
    "/survey",
    response_model=StudentProfile,
    summary="Submit Amplitude survey",
    description=(
        "**Purpose:** Persist the five historical inputs used for Amplitude categorization.\n\n"
        "**Caller:** Frontend.\n\n"
        "**Peer services:** none.\n\n"
        "**Request body:**\n"
        "```json\n"
        "{\n"
        '  "user_id": "mock-student-class-a",\n'
        '  "grade": 7,\n'
        '  "completed_chapters_count": 4,\n'
        '  "past_grade_marks_range": "50_75",\n'
        '  "study_hours_per_week": 5.0,\n'
        '  "self_confidence": 3\n'
        "}\n"
        "```\n"
        "`past_grade_marks_range`: `BELOW_50` | `50_75` | `ABOVE_75`. "
        "`self_confidence`: 1–5. `grade` may be injected for local testing.\n\n"
        "**How to Test:** `/docs` → Try it out → `mock-student-class-a` → Execute → 200."
    ),
)
def submit_survey(
    payload: AmplitudeSurveyRequest,
    container: Container = Depends(get_container),
) -> StudentProfile:
    user_id = resolve_student_id(payload.user_id)
    grade = resolve_grade(payload.grade)
    return container.amplitude_service.save_survey(
        user_id=user_id,
        grade=grade,
        completed_chapters_count=payload.completed_chapters_count,
        past_grade_marks_range=payload.past_grade_marks_range,
        study_hours_per_week=payload.study_hours_per_week,
        self_confidence=payload.self_confidence,
    )


@router.get(
    "/quiz",
    response_model=PlacementQuizResponse,
    summary="Get fixed 10-item Amplitude quiz",
    description=(
        "**Purpose:** Return the grade-stable fixed 10 bank items (answer keys stripped).\n\n"
        "**Caller:** Frontend. **No BKT.**\n\n"
        "**Query:** `grade` (6–9) — local testing override to select the grade's fixed set.\n\n"
        "**How to Test:** `grade=7` → expect `count=10` (409 if bank too small)."
    ),
    responses={
        200: {"description": "Fixed quiz items."},
        409: {"model": ErrorDetail, "description": "Not enough approved bank items."},
    },
)
def amplitude_quiz(
    grade: int = Query(default=DEFAULT_GRADE, ge=6, le=9),
    container: Container = Depends(get_container),
) -> PlacementQuizResponse:
    resolved = resolve_grade(grade)
    try:
        questions = container.amplitude_service.diagnostic_quiz(resolved)
    except AmplitudeQuizUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return PlacementQuizResponse(
        grade=resolved,
        count=len(questions),
        questions=[_quiz_item(item) for item in questions],
    )


@router.post(
    "/evaluate",
    response_model=AmplitudeEvaluation,
    summary="Evaluate Amplitude category",
    description=(
        "**Purpose:** Grade the fixed 10 answers; persist "
        "`BASIC` | `INTERMEDIATE` | `ADVANCED` "
        "(60% quiz + 40% historical composite).\n\n"
        "**Caller:** Frontend.\n\n"
        "**Request:** survey fields + `answers: { \"<question_id>\": \"A\" }`.\n\n"
        "**How to Test:** After `/quiz`, map every id → answer → Execute → then "
        "`GET .../students/{id}/initial-category`."
    ),
)
def evaluate_amplitude(
    payload: AmplitudeEvaluateRequest,
    container: Container = Depends(get_container),
) -> AmplitudeEvaluation:
    user_id = resolve_student_id(payload.user_id)
    grade = resolve_grade(payload.grade)
    try:
        return container.amplitude_service.evaluate(
            user_id=user_id,
            grade=grade,
            completed_chapters_count=payload.completed_chapters_count,
            past_grade_marks_range=payload.past_grade_marks_range,
            study_hours_per_week=payload.study_hours_per_week,
            self_confidence=payload.self_confidence,
            answers=payload.answers,
        )
    except AmplitudeQuizUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
