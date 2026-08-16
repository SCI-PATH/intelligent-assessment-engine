"""Build the Component 4 (BKT Analytics) event after a graded answer.

Unified JSON strategy — every event always contains the same keys. Fields that
do not apply to the current ``question_type`` are explicitly ``null``.

Component 4 base contract (always present):
  user_id, topic_id, is_correct, question_type, question_id,
  similarity_score, distractor_tag, distractor_label,
  response_time_s, difficulty_level, subtopic_id,
  chosen_distractor_text, source

Component 2 enrichments for all four question types (null when N/A):
  error_category, detailed_explanation, missed_blanks

Persisted to ``question_engine.analytics_events``; optional HTTP POST is
commented out until Component 4's ingest URL is wired via ``ANALYTICS_BASE_URL``.
"""

from __future__ import annotations

import math
from typing import Any

from iae.core.models import DistractorTag, GradeResult, MCQPayload, Question, QuestionType
from iae.core.protocols import IEmbedder, ILlmJson
from iae.core.settings import get_settings
from iae.prompts import render

# httpx is imported so the integration line below is ready to uncomment.
import httpx  # noqa: F401

_NEAR_MISS_MIN = 0.72
_MISCONCEPTION_MIN = 0.40
_SOURCE = "question_engine_v1"

_TAG_CUE = {
    DistractorTag.NEAR_MISS: "a near-miss: the chosen idea is close to the correct concept but not quite right",
    DistractorTag.MISCONCEPTION: "a common misconception about this topic",
    DistractorTag.COMPLETE_MISS: "a complete miss, unrelated to the target concept",
}

# Stable key order for Component 4 consumers.
_CONTRACT_KEYS = (
    "user_id",
    "topic_id",
    "question_id",
    "question_type",
    "is_correct",
    "similarity_score",
    "distractor_tag",
    "distractor_label",
    "chosen_distractor_text",
    "error_category",
    "detailed_explanation",
    "missed_blanks",
    "response_time_s",
    "difficulty_level",
    "subtopic_id",
    "source",
)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _mcq_option_text(payload: MCQPayload, letter: str) -> str:
    key = (letter or "").strip().upper()
    return str(payload.options.get(key) or "").strip()


def _nonempty_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
    response_time_s: float | None = None,
    embedder: IEmbedder | None = None,
    llm: ILlmJson | None = None,
) -> dict[str, Any]:
    """Build the unified Component 4 payload for any of the four question types."""
    qtype = question.question_type

    similarity_score: float | None = None
    distractor_tag: str | None = None
    distractor_label: str | None = None
    chosen_distractor_text: str | None = None
    error_category: str | None = None
    detailed_explanation: str | None = None
    missed_blanks: dict[str, str] | None = None

    if qtype == QuestionType.MCQ:
        if not grade.is_correct:
            payload_mcq: MCQPayload = question.payload  # type: ignore[assignment]
            chosen_distractor_text = _nonempty_str(_mcq_option_text(payload_mcq, student_answer))
            distractor_tag = _nonempty_str(grade.distractor_tag)
            distractor_label = _nonempty_str(grade.distractor_label)
            if distractor_tag is None:
                if embedder is None:
                    tag = DistractorTag.COMPLETE_MISS
                else:
                    tag, _ = classify_mcq_distractor(
                        question=question,
                        student_answer=student_answer,
                        embedder=embedder,
                    )
                distractor_tag = tag.value
                distractor_label = explain_mcq_distractor(
                    question=question,
                    student_answer=student_answer,
                    tag=tag,
                    llm=llm,
                )

    elif qtype == QuestionType.SHORT_ANSWER:
        similarity_score = float(grade.accuracy_score)
        error_category = _nonempty_str(grade.error_category)
        detailed_explanation = _nonempty_str(grade.detailed_explanation)

    elif qtype == QuestionType.MULTI_BLANK:
        similarity_score = float(grade.accuracy_score)
        error_category = _nonempty_str(grade.error_category)
        if grade.missed_blanks:
            missed_blanks = {str(k): str(v) for k, v in grade.missed_blanks.items()}

    elif qtype == QuestionType.TRUE_FALSE:
        detailed_explanation = _nonempty_str(grade.detailed_explanation) or _nonempty_str(
            grade.concept_explanation
        )

    response_time: float | None = None
    if response_time_s is not None:
        response_time = max(0.0, float(response_time_s))

    payload: dict[str, Any] = {
        "user_id": str(user_id),
        "topic_id": question.topic_id or "",
        "question_id": question.id,
        "question_type": qtype.value,
        "is_correct": bool(grade.is_correct),
        "similarity_score": similarity_score,
        "distractor_tag": distractor_tag,
        "distractor_label": distractor_label,
        "chosen_distractor_text": chosen_distractor_text,
        "error_category": error_category,
        "detailed_explanation": detailed_explanation,
        "missed_blanks": missed_blanks,
        "response_time_s": response_time,
        "difficulty_level": int(question.dok_level),
        "subtopic_id": _nonempty_str(question.sub_concept),
        "source": _SOURCE,
    }
    for key in _CONTRACT_KEYS:
        payload.setdefault(key, None)
    return payload


def _component4_submit_url(base: str) -> str:
    """Resolve Component 4's assessment-submit URL from ANALYTICS_BASE_URL."""
    url = base.strip().rstrip("/")
    if url.endswith("/assessment-submit"):
        return url
    return f"{url}/api/v1/assessment-submit"


def send_analytics_event(payload: dict[str, Any]) -> None:
    """POST the unified payload to Component 4 ``POST /api/v1/assessment-submit``."""
    base = get_settings().analytics_base_url
    if not base:
        return
    url = _component4_submit_url(base)
    try:
        httpx.post(url, json=payload, timeout=5.0)
    except Exception:
        # Diagnostic flow must not fail if Component 4 is briefly unreachable.
        return
