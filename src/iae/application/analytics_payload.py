"""Build the Component 3 analytics event after a graded answer.

``send_analytics_event`` contains the real HTTP call, commented out until
the analytics service is wired. Persistence is handled separately.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any

from iae.core.models import GradeResult, MCQPayload, Question, QuestionType
from iae.core.protocols import IEmbedder, ILlmJson
from iae.core.settings import get_settings
from iae.prompts import render

# httpx is imported so the integration line below is ready to uncomment.
import httpx  # noqa: F401

_NEAR_MISS_MIN = 0.72
_MISCONCEPTION_MIN = 0.40


class DistractorTag(str, Enum):
    NEAR_MISS = "NEAR_MISS"
    MISCONCEPTION = "MISCONCEPTION"
    COMPLETE_MISS = "COMPLETE_MISS"


_TAG_CUE = {
    DistractorTag.NEAR_MISS: "a near-miss: the chosen idea is close to the correct concept but not quite right",
    DistractorTag.MISCONCEPTION: "a common misconception about this topic",
    DistractorTag.COMPLETE_MISS: "a complete miss, unrelated to the target concept",
}


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _mcq_option_text(payload: MCQPayload, letter: str) -> str:
    key = (letter or "").strip().upper()
    return str(payload.options.get(key) or "").strip()


def classify_mcq_distractor(
    *,
    question: Question,
    student_answer: str,
    embedder: IEmbedder,
) -> tuple[DistractorTag, float]:
    """Return (tag, cosine similarity of chosen vs correct option text)."""
    payload: MCQPayload = question.payload  # type: ignore[assignment]
    chosen_letter = student_answer.strip().upper()
    correct_letter = payload.correct_answer.strip().upper()
    chosen_text = _mcq_option_text(payload, chosen_letter)
    correct_text = _mcq_option_text(payload, correct_letter)
    if not chosen_text or chosen_letter not in payload.options:
        return DistractorTag.COMPLETE_MISS, 0.0

    vectors = embedder.embed([chosen_text, correct_text, payload.question])
    similarity = _cosine(vectors[0], vectors[1])
    if similarity >= _NEAR_MISS_MIN:
        return DistractorTag.NEAR_MISS, similarity
    if similarity >= _MISCONCEPTION_MIN:
        return DistractorTag.MISCONCEPTION, similarity
    return DistractorTag.COMPLETE_MISS, similarity


def _fallback_label(*, chosen_text: str, correct_text: str, tag: DistractorTag) -> str:
    return (
        f"The student selected '{chosen_text}' rather than '{correct_text}', "
        f"which indicates {_TAG_CUE[tag]}."
    )


def explain_mcq_distractor(
    *,
    question: Question,
    student_answer: str,
    tag: DistractorTag,
    llm: ILlmJson | None,
) -> str:
    payload: MCQPayload = question.payload  # type: ignore[assignment]
    chosen_text = _mcq_option_text(payload, student_answer)
    correct_text = _mcq_option_text(payload, payload.correct_answer)
    fallback = _fallback_label(chosen_text=chosen_text or student_answer, correct_text=correct_text, tag=tag)
    if llm is None or not chosen_text:
        return fallback
    prompt = render(
        "analytics/distractor_label.jinja",
        question=payload.question,
        correct_text=correct_text,
        chosen_text=chosen_text,
        distractor_tag=tag.value,
    )
    try:
        result = llm.generate_json(prompt, temperature=0.15)
        label = str(result.get("distractor_label") or "").strip()
        sentences = [part.strip() for part in label.replace("!", ".").split(".") if part.strip()]
        if not sentences:
            return fallback
        return ". ".join(sentences[:2]) + "."
    except Exception:
        return fallback


def build_analytics_payload(
    *,
    user_id: str,
    question: Question,
    grade: GradeResult,
    student_answer: str,
    embedder: IEmbedder | None = None,
    llm: ILlmJson | None = None,
) -> dict[str, Any]:
    """Exact JSON Component 3 will consume."""
    payload: dict[str, Any] = {
        "user_id": user_id,
        "topic_id": question.topic_id or "",
        "is_correct": bool(grade.is_correct),
        "question_id": question.id,
        "question_type": question.question_type.value,
        "similarity_score": None,
        "distractor_tag": None,
        "distractor_label": None,
    }

    if question.question_type in (QuestionType.SHORT_ANSWER, QuestionType.MULTI_BLANK):
        payload["similarity_score"] = float(grade.accuracy_score)

    if question.question_type == QuestionType.MCQ and not grade.is_correct:
        if embedder is None:
            tag = DistractorTag.COMPLETE_MISS
        else:
            tag, _ = classify_mcq_distractor(
                question=question,
                student_answer=student_answer,
                embedder=embedder,
            )
        payload["distractor_tag"] = tag.value
        payload["distractor_label"] = explain_mcq_distractor(
            question=question,
            student_answer=student_answer,
            tag=tag,
            llm=llm,
        )

    return payload


def send_analytics_event(payload: dict[str, Any]) -> None:
    """POST the event to Component 3. Left commented until that service exists."""
    url = get_settings().analytics_base_url
    if not url:
        return
    # httpx.post(url, json=payload, timeout=5.0)
    return
