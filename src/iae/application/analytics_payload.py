"""Build the Component 4 (BKT Analytics) event after a graded answer.

Unified JSON strategy — every event always contains the same keys. Fields that
do not apply to the current ``question_type`` are explicitly ``null``.

Contract: docs/COMPONENT2_COMPONENT4_INTEGRATION.md
"""

from __future__ import annotations

import math
from typing import Any

from iae.domain.models import (
    DistractorTag,
    GradeResult,
    MCQPayload,
    OptionDiagnostic,
    Question,
    QuestionType,
    TrueFalsePayload,
)
from iae.domain.protocols import IEmbedder, ILlmJson
from iae.prompts import render

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


def _lookup_mcq_diagnostics(
    question: Question,
    student_answer: str,
) -> tuple[str | None, str | None]:
    payload: MCQPayload = question.payload  # type: ignore[assignment]
    letter = student_answer.strip().upper()
    entry = (payload.option_diagnostics or {}).get(letter)
    if entry is None:
        return None, None
    if isinstance(entry, OptionDiagnostic):
        return entry.distractor_tag.value, entry.distractor_label
    if isinstance(entry, dict):
        tag = _nonempty_str(entry.get("distractor_tag"))
        label = _nonempty_str(entry.get("distractor_label"))
        return tag, label
    return None, None


def build_analytics_payload(
    *,
    user_id: str,
    question: Question,
    grade: GradeResult,
    student_answer: str,
    response_time_s: float | None = None,
    embedder: IEmbedder | None = None,
    llm: ILlmJson | None = None,
    chapter_ids: list[str] | None = None,
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
            if distractor_tag is None or distractor_label is None:
                stored_tag, stored_label = _lookup_mcq_diagnostics(question, student_answer)
                distractor_tag = distractor_tag or stored_tag
                distractor_label = distractor_label or stored_label
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
                distractor_label = distractor_label or explain_mcq_distractor(
                    question=question,
                    student_answer=student_answer,
                    tag=tag,
                    llm=llm,
                )

    elif qtype == QuestionType.SHORT_ANSWER:
        similarity_score = float(grade.accuracy_score)
        error_category = _nonempty_str(grade.error_category)
        if grade.is_correct:
            error_category = error_category or "NO_ERROR"
            detailed_explanation = None
        else:
            detailed_explanation = _nonempty_str(grade.detailed_explanation)

    elif qtype == QuestionType.MULTI_BLANK:
        similarity_score = float(grade.accuracy_score)
        error_category = _nonempty_str(grade.error_category)
        if grade.is_correct:
            error_category = error_category or "NO_ERROR"
            missed_blanks = None
        elif grade.missed_blanks:
            missed_blanks = {str(k): str(v) for k, v in grade.missed_blanks.items()}

    elif qtype == QuestionType.TRUE_FALSE:
        if not grade.is_correct:
            tf_payload: TrueFalsePayload = question.payload  # type: ignore[assignment]
            chosen = student_answer.strip()
            lower = chosen.lower()
            if lower.startswith("t"):
                chosen_distractor_text = "True"
            elif lower.startswith("f"):
                chosen_distractor_text = "False"
            else:
                chosen_distractor_text = _nonempty_str(chosen)
            distractor_tag = _nonempty_str(grade.distractor_tag)
            distractor_label = _nonempty_str(grade.distractor_label)
            if distractor_tag is None and tf_payload.distractor_tag is not None:
                tag = tf_payload.distractor_tag
                distractor_tag = tag.value if isinstance(tag, DistractorTag) else str(tag)
            if distractor_label is None and tf_payload.distractor_label:
                distractor_label = str(tf_payload.distractor_label).strip()
            if distractor_tag is None:
                distractor_tag = DistractorTag.MISCONCEPTION.value
            if distractor_label is None:
                distractor_label = "Selected the incorrect True/False polarity"
            detailed_explanation = (
                _nonempty_str(grade.detailed_explanation)
                or _nonempty_str(grade.concept_explanation)
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
    if chapter_ids:
        payload["chapter_ids"] = list(chapter_ids)
    return payload


def send_analytics_event(payload: dict[str, Any]) -> None:
    """No-op: Component 4 submit is owned by ``Component4Client.submit_assessment``."""
    _ = payload
    return
