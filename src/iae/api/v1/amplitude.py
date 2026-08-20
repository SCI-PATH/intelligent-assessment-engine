"""Amplitude Test routes under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from iae.api.bootstrap import Container
from iae.api.deps import get_container
from iae.api.schemas import (
    AmplitudeCategoryResponse,
    AmplitudeEvaluateRequest,
    AmplitudeSurveyRequest,
    ErrorDetail,
    PlacementQuizItem,
    PlacementQuizResponse,
)
from iae.core.curriculum import DEFAULT_GRADE
from iae.core.models import AmplitudeEvaluation, Question, StudentProfile
from iae.services.amplitude_service import AmplitudeQuizUnavailable

router = APIRouter(prefix="/api/v1/amplitude", tags=["Amplitude"])


def _public_prompt(question: Question) -> dict:
    payload = question.payload.model_dump(mode="json")
    for secret in ("correct_answer", "ideal_answer", "answers", "keywords"):
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
        "Persists five historical inputs: grade, past marks band, chapters completed, "
        "study hours/week, and self-confidence (1–5)."
    ),
)
def submit_survey(
    payload: AmplitudeSurveyRequest,
    container: Container = Depends(get_container),
) -> StudentProfile:
    return container.amplitude_service.save_survey(
        user_id=payload.user_id,
        grade=payload.grade,
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
        "Same question IDs for every student in a grade (seeded once from the approved bank). "
        "Answer keys are stripped. No BKT."
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
    try:
        questions = container.amplitude_service.diagnostic_quiz(grade)
    except AmplitudeQuizUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return PlacementQuizResponse(
        grade=grade,
        count=len(questions),
        questions=[_quiz_item(item) for item in questions],
    )


@router.post(
    "/evaluate",
    response_model=AmplitudeEvaluation,
    summary="Evaluate Amplitude category",
    description=(
        "Grades the fixed 10 answers, blends 60% quiz + 40% historical composite, "
        "and persists `BASIC` | `INTERMEDIATE` | `ADVANCED` on the student profile."
    ),
)
def evaluate_amplitude(
    payload: AmplitudeEvaluateRequest,
    container: Container = Depends(get_container),
) -> AmplitudeEvaluation:
    try:
        return container.amplitude_service.evaluate(
            user_id=payload.user_id,
            grade=payload.grade,
            completed_chapters_count=payload.completed_chapters_count,
            past_grade_marks_range=payload.past_grade_marks_range,
            study_hours_per_week=payload.study_hours_per_week,
            self_confidence=payload.self_confidence,
            answers=payload.answers,
        )
    except AmplitudeQuizUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.get(
    "/students/{student_id}/initial-category",
    response_model=AmplitudeCategoryResponse,
    summary="Get student initial Amplitude category",
    responses={404: {"model": ErrorDetail}},
)
def get_initial_category(
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
