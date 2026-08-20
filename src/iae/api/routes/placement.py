"""Initial placement: survey, 10-item diagnostic quiz, weighted category."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from iae.api.bootstrap import Container
from iae.api.schemas import (
    ErrorDetail,
    PlacementEvaluateRequest,
    PlacementQuizItem,
    PlacementQuizResponse,
    PlacementSurveyRequest,
)
from iae.application.placement import PlacementQuizUnavailable
from iae.core.curriculum import DEFAULT_GRADE
from iae.core.models import PlacementEvaluation, Question, StudentProfile

router = APIRouter(prefix="/assessment/placement", tags=["Placement"])


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


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
    summary="Submit placement survey",
    description=(
        "Stores the student's self-reported grade, chapters completed, and past "
        "marks band on `question_engine.users`."
    ),
    responses={200: {"description": "Updated student profile."}},
)
def submit_survey(
    payload: PlacementSurveyRequest,
    container: Container = Depends(get_container),
) -> StudentProfile:
    """Persist placement survey fields on the student profile."""
    return container.placement_service.save_survey(
        user_id=payload.user_id,
        grade=payload.grade,
        completed_chapters_count=payload.completed_chapters_count,
        past_grade_marks_range=payload.past_grade_marks_range,
    )


@router.get(
    "/quiz",
    response_model=PlacementQuizResponse,
    summary="Get placement diagnostic quiz",
    description=(
        "Returns up to 10 approved bank questions for the grade. "
        "Answer keys are stripped from each `prompt`."
    ),
    responses={
        200: {"description": "Quiz items ready to show the student."},
        409: {
            "model": ErrorDetail,
            "description": "Not enough approved bank items for this grade.",
        },
    },
)
def diagnostic_quiz(
    grade: int = Query(
        default=DEFAULT_GRADE,
        ge=6,
        le=9,
        description="Grade year for the quiz.",
        examples=[7],
    ),
    container: Container = Depends(get_container),
) -> PlacementQuizResponse:
    """Return a 10-item foundational quiz with answer keys stripped."""
    try:
        questions = container.placement_service.diagnostic_quiz(grade)
    except PlacementQuizUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return PlacementQuizResponse(
        grade=grade,
        count=len(questions),
        questions=[_quiz_item(item) for item in questions],
    )


@router.post(
    "/evaluate",
    response_model=PlacementEvaluation,
    summary="Evaluate placement category (team integration)",
    description=(
        "**Cross-component contract.** Computes a weighted score "
        "(70% quiz + 30% past marks), maps it to `WEAK` | `AVERAGE` | `ADVANCED`, "
        "persists `question_engine.placement_evaluations`, and updates "
        "`question_engine.users.placement_category` / `placement_score`.\n\n"
        "Response always includes:\n"
        "- `category` — exact enum string `WEAK` | `AVERAGE` | `ADVANCED`\n"
        "- `weighted_score` — final blended score in `[0, 1]`\n"
        "- `quiz_score` — `quiz_correct / quiz_total`\n"
        "- `past_score` — mapped from `past_grade_marks_range`"
    ),
    responses={
        200: {
            "description": (
                "Placement evaluation with category WEAK | AVERAGE | ADVANCED "
                "and score breakdown."
            )
        }
    },
)
def evaluate_placement(
    payload: PlacementEvaluateRequest,
    container: Container = Depends(get_container),
) -> PlacementEvaluation:
    """Return WEAK / AVERAGE / ADVANCED plus weighted/quiz/past scores for integrators."""
    return container.placement_service.evaluate(
        user_id=payload.user_id,
        grade=payload.grade,
        completed_chapters_count=payload.completed_chapters_count,
        past_grade_marks_range=payload.past_grade_marks_range,
        quiz_correct=payload.quiz_correct,
        quiz_total=payload.quiz_total,
    )
