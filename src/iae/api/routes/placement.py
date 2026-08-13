"""Initial placement: survey, 10-item diagnostic quiz, weighted category."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from iae.api.bootstrap import Container
from iae.api.schemas import (
    PlacementEvaluateRequest,
    PlacementQuizItem,
    PlacementQuizResponse,
    PlacementSurveyRequest,
)
from iae.application.placement import PlacementQuizUnavailable
from iae.core.curriculum import DEFAULT_GRADE
from iae.core.models import PlacementEvaluation, Question, StudentProfile

router = APIRouter(prefix="/assessment/placement", tags=["placement"])


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


@router.post("/survey", response_model=StudentProfile)
def submit_survey(
    payload: PlacementSurveyRequest,
    container: Container = Depends(get_container),
) -> StudentProfile:
    return container.placement_service.save_survey(
        user_id=payload.user_id,
        grade=payload.grade,
        completed_chapters_count=payload.completed_chapters_count,
        past_grade_marks_range=payload.past_grade_marks_range,
    )


@router.get("/quiz", response_model=PlacementQuizResponse)
def diagnostic_quiz(
    grade: int = Query(default=DEFAULT_GRADE, ge=6, le=9),
    container: Container = Depends(get_container),
) -> PlacementQuizResponse:
    try:
        questions = container.placement_service.diagnostic_quiz(grade)
    except PlacementQuizUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return PlacementQuizResponse(
        grade=grade,
        count=len(questions),
        questions=[_quiz_item(item) for item in questions],
    )


@router.post("/evaluate", response_model=PlacementEvaluation)
def evaluate_placement(
    payload: PlacementEvaluateRequest,
    container: Container = Depends(get_container),
) -> PlacementEvaluation:
    return container.placement_service.evaluate(
        user_id=payload.user_id,
        grade=payload.grade,
        completed_chapters_count=payload.completed_chapters_count,
        past_grade_marks_range=payload.past_grade_marks_range,
        quiz_correct=payload.quiz_correct,
        quiz_total=payload.quiz_total,
    )
