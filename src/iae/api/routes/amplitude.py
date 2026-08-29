"""Aptitude Diagnostic Test routes under /api/v1/assessment-engine.

URL path stays `/amplitude` so existing frontend/C1 clients keep working.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from iae.api.bootstrap import Container
from iae.api.deps import get_container
from iae.api.integration_ids import resolve_grade, resolve_student_id
from iae.api.schemas import (
    AmplitudeEvaluateRequest,
    AmplitudeSurveyRequest,
    ErrorDetail,
    PlacementQuizItem,
    PlacementQuizResponse,
)
from iae.application.amplitude_service import AmplitudeQuizUnavailable, AmplitudeSurveyInvalid
from iae.domain.chapter_catalog import chapters_for_grade
from iae.domain.curriculum import DEFAULT_GRADE
from iae.domain.models import AmplitudeEvaluation, Question, StudentProfile

router = APIRouter(
    prefix="/api/v1/assessment-engine/amplitude",
    tags=["Aptitude Diagnostic Test"],
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


@router.get(
    "/chapters",
    summary="List all chapters for a grade (Aptitude survey multi-select)",
    description=(
        "Returns every canonical chapter_id for the grade so the frontend can "
        "render the completed-chapters multi-select. Selecting none is valid."
    ),
)
def list_amplitude_chapters(
    grade: int = Query(default=7, ge=6, le=9, examples=[7]),
) -> dict:
    resolved = resolve_grade(grade)
    rows = chapters_for_grade(resolved)
    return {
        "grade": resolved,
        "count": len(rows),
        "chapters": [
            {
                "chapter_id": r.chapter_id,
                "chapter": r.chapter,
                "chapter_title": r.chapter_title,
                "topic_ids": list(r.topic_ids),
            }
            for r in rows
        ],
    }


@router.post(
    "/survey",
    response_model=StudentProfile,
    summary="Submit Aptitude survey",
    description=(
        "**Purpose:** Persist pre-use intake inputs (mandatory past marks + chapter multi-select).\n\n"
        "**Caller:** Frontend (post registration / before lessons).\n\n"
        "`past_grade_marks_range` is **required**. "
        "`completed_chapter_ids` may be `[]` if the student has not started the grade.\n\n"
        "**How to Test:** `/docs` → Try it out → Execute → 200."
    ),
    responses={400: {"model": ErrorDetail}},
)
def submit_survey(
    payload: AmplitudeSurveyRequest,
    container: Container = Depends(get_container),
) -> StudentProfile:
    user_id = resolve_student_id(payload.user_id)
    grade = resolve_grade(payload.grade)
    try:
        return container.amplitude_service.save_survey(
            user_id=user_id,
            grade=grade,
            past_grade_marks_range=payload.past_grade_marks_range,
            completed_chapter_ids=payload.completed_chapter_ids,
            completed_chapters_count=payload.completed_chapters_count,
            study_hours_per_week=payload.study_hours_per_week,
            self_confidence=payload.self_confidence,
            science_self_efficacy=payload.science_self_efficacy,
            prerequisite_ready_count=payload.prerequisite_ready_count,
        )
    except AmplitudeSurveyInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get(
    "/quiz",
    response_model=PlacementQuizResponse,
    summary="Get fixed 10-item Aptitude quiz",
    description=(
        "**Purpose:** Return the grade-stable fixed 10 Aptitude items (MCQ/TrueFalse only).\n\n"
        "**Caller:** Frontend. **No BKT.** Sourced from `amplitude_questions`, not the adaptive bank.\n\n"
        "**How to Test:** `grade=7` → expect `count=10` (409 if bank not generated)."
    ),
    responses={
        200: {"description": "Fixed quiz items."},
        409: {"model": ErrorDetail, "description": "Aptitude bank missing for grade."},
    },
)
def amplitude_quiz(
    grade: int = Query(default=7, ge=6, le=9, examples=[7]),
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
    summary="Evaluate Aptitude category",
    description=(
        "**Purpose:** Grade the fixed 10 answers; persist "
        "`BASIC` | `INTERMEDIATE` | `ADVANCED` "
        "(60% quiz + 40% historical composite).\n\n"
        "**Caller:** Frontend.\n\n"
        "**Request:** survey fields + `answers: { \"<question_id>\": \"A\" }`.\n\n"
        "**How to Test:** After `/quiz`, map every id → answer → Execute → then "
        "`GET .../students/{id}/initial-category`."
    ),
    responses={400: {"model": ErrorDetail}, 409: {"model": ErrorDetail}},
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
            past_grade_marks_range=payload.past_grade_marks_range,
            completed_chapter_ids=payload.completed_chapter_ids,
            completed_chapters_count=payload.completed_chapters_count,
            study_hours_per_week=payload.study_hours_per_week,
            self_confidence=payload.self_confidence,
            science_self_efficacy=payload.science_self_efficacy,
            prerequisite_ready_count=payload.prerequisite_ready_count,
            answers=payload.answers,
        )
    except AmplitudeSurveyInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except AmplitudeQuizUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
