"""Grading pipeline: deterministic for structural items, LLM-judged for prose.

Every question type attaches diagnostic fields on ``GradeResult`` so attempts
and analytics_events can persist them.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from uuid import uuid4

from iae.application.analytics_payload import classify_mcq_distractor, explain_mcq_distractor
from iae.core.models import (
    DistractorTag,
    GradeResult,
    MultiBlankErrorCategory,
    MultiBlankPayload,
    Question,
    QuestionType,
    ShortAnswerErrorCategory,
    ShortAnswerPayload,
    TrueFalsePayload,
)
from iae.core.protocols import IEmbedder, ILlmJson
from iae.prompts import render

_PASS_THRESHOLD = 0.8
_DEBUG_LOG_PATH = Path("debug-21ced4.log")
_SA_CATEGORIES = {item.value for item in ShortAnswerErrorCategory}


def _debug_log(*, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "sessionId": "21ced4",
        "runId": "initial",
        "hypothesisId": hypothesis_id,
        "id": f"log_{uuid4().hex}",
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass


def _clamp_sentences(text: str, *, max_sentences: int = 2) -> str:
    sentences = [part.strip() for part in text.replace("!", ".").split(".") if part.strip()]
    if not sentences:
        return ""
    return ". ".join(sentences[:max_sentences]) + "."


def _keywords_missing(keywords: list[str], student_norm: str) -> list[str]:
    missing: list[str] = []
    for keyword in keywords:
        token = (keyword or "").strip()
        if token and token.lower() not in student_norm:
            missing.append(token)
    return missing


def _parse_sa_category(raw: object, *, score: float, missing: list[str]) -> str:
    value = str(raw or "").strip().upper()
    if value in _SA_CATEGORIES:
        return value
    if score >= _PASS_THRESHOLD and not missing:
        return ShortAnswerErrorCategory.NO_ERROR.value
    if missing:
        return ShortAnswerErrorCategory.MISSING_KEYWORDS.value
    if score <= 0.15:
        return ShortAnswerErrorCategory.COMPLETELY_IRRELEVANT.value
    return ShortAnswerErrorCategory.CONCEPTUAL_MISCONCEPTION.value


class GradingService:
    """Implements ``IGradingService``."""

    def __init__(self, llm: ILlmJson, embedder: IEmbedder | None = None) -> None:
        self._llm = llm
        self._embedder = embedder

    def grade(self, question: Question, student_answer: str) -> GradeResult:
        if question.question_type == QuestionType.MCQ:
            return self._grade_mcq(question, student_answer)
        if question.question_type == QuestionType.TRUE_FALSE:
            return self._grade_true_false(question, student_answer)
        if question.question_type == QuestionType.MULTI_BLANK:
            return self._grade_multi_blank(question, student_answer)
        return self._grade_short_answer(question, student_answer)

    # ---- deterministic graders -------------------------------------------------

    def _grade_mcq(self, question: Question, student_answer: str) -> GradeResult:
        correct = question.payload.correct_answer.strip().upper()
        chosen = student_answer.strip().upper()
        is_correct = chosen == correct
        result = GradeResult(
            accuracy_score=1.0 if is_correct else 0.0,
            is_correct=is_correct,
            feedback="Correct." if is_correct else f"Incorrect. The right answer is {correct}.",
        )
        if is_correct:
            return result
        tag = DistractorTag.COMPLETE_MISS
        if self._embedder is not None:
            try:
                tag, _ = classify_mcq_distractor(
                    question=question,
                    student_answer=student_answer,
                    embedder=self._embedder,
                )
            except Exception:
                tag = DistractorTag.COMPLETE_MISS
        result.distractor_tag = tag.value
        try:
            result.distractor_label = explain_mcq_distractor(
                question=question,
                student_answer=student_answer,
                tag=tag,
                llm=self._llm,
            )
        except Exception:
            result.distractor_label = (
                f"The chosen option differs from {correct}, indicating a complete miss."
            )
        return result

    def _grade_true_false(self, question: Question, student_answer: str) -> GradeResult:
        payload: TrueFalsePayload = question.payload  # type: ignore[assignment]
        correct = payload.correct_answer.strip().lower()
        chosen = student_answer.strip().lower()
        is_correct = bool(chosen) and chosen.startswith(correct[0])
        _debug_log(
            hypothesis_id="H1",
            location="src/iae/application/grading.py:_grade_true_false",
            message="True/False grading computed outcome",
            data={
                "question_id": question.id,
                "correct_answer": correct,
                "student_answer_raw": student_answer,
                "student_answer_normalized": chosen,
                "is_correct": is_correct,
            },
        )
        explanation = None if is_correct else self._true_false_explanation(payload)
        return GradeResult(
            accuracy_score=1.0 if is_correct else 0.0,
            is_correct=is_correct,
            feedback="Correct." if is_correct else f"Incorrect. The statement is {correct.title()}.",
            concept_explanation=explanation,
        )

    def _true_false_explanation(self, payload: TrueFalsePayload) -> str:
        fallback = f"The statement is {payload.correct_answer}."
        prompt = render(
            "grading/true_false_concept.jinja",
            question=payload.question,
            correct_answer=payload.correct_answer,
        )
        try:
            result = self._llm.generate_json(prompt, temperature=0.15)
            text = _clamp_sentences(str(result.get("concept_explanation") or ""), max_sentences=1)
            return text or fallback
        except Exception:
            return fallback

    def _grade_multi_blank(self, question: Question, student_answer: str) -> GradeResult:
        payload: MultiBlankPayload = question.payload  # type: ignore[assignment]
        student_blanks = self._parse_blanks(student_answer, expected=len(payload.answers))
        ideal = [a.strip().lower() for a in payload.answers]
        provided = [b.strip().lower() for b in student_blanks]
        provided += [""] * (len(ideal) - len(provided))
        hits = sum(1 for given, expected in zip(provided, ideal) if given == expected)
        score = hits / len(ideal) if ideal else 0.0
        missed_blanks = {
            str(index): payload.answers[index]
            for index, (given, expected) in enumerate(zip(provided, ideal))
            if given != expected
        }
        if score == 1.0:
            category = MultiBlankErrorCategory.NO_ERROR.value
        elif score == 0.0:
            category = MultiBlankErrorCategory.FULL_MISCONCEPTION.value
        else:
            category = MultiBlankErrorCategory.PARTIAL_MASTERY.value
        return GradeResult(
            accuracy_score=score,
            is_correct=score >= _PASS_THRESHOLD,
            feedback=f"{hits} of {len(ideal)} blanks correct.",
            error_category=category,
            missed_blanks=missed_blanks or None,
        )

    @staticmethod
    def _parse_blanks(raw: str, *, expected: int) -> list[str]:
        """Accept either a JSON array or a delimiter-separated string."""
        raw = raw.strip()
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except json.JSONDecodeError:
                pass
        return [part.strip() for part in re.split(r"[|;,\n]", raw) if part.strip()][:expected]

    # ---- LLM-judged grader -----------------------------------------------------

    @staticmethod
    def _feedback_matches_outcome(feedback: str, *, is_correct: bool) -> str:
        text = (feedback or "").strip()
        lowered = text.lower()
        negative_cues = ("incorrect", "does not", "not correct", "wrong", "missing")
        positive_cues = ("correct", "good", "clear", "well done")

        if is_correct and any(cue in lowered for cue in negative_cues):
            return "Correct. The response meets the expected understanding."
        if (not is_correct) and any(cue in lowered for cue in positive_cues):
            return "Not fully correct yet. Review the key concept and try again."
        return text or ("Correct." if is_correct else "Not fully correct yet.")

    def _grade_short_answer(self, question: Question, student_answer: str) -> GradeResult:
        payload: ShortAnswerPayload = question.payload  # type: ignore[assignment]
        if not student_answer or not student_answer.strip():
            return GradeResult(
                accuracy_score=0.0,
                is_correct=False,
                feedback="No answer provided.",
                reasoning="The response is blank, so no concept evidence could be evaluated.",
                error_category=ShortAnswerErrorCategory.COMPLETELY_IRRELEVANT.value,
                missing_keywords=list(payload.keywords or []),
                detailed_explanation="No answer was provided, so none of the required concepts were demonstrated.",
            )

        student_norm = " ".join(student_answer.lower().split())
        ideal_norm = " ".join(payload.ideal_answer.lower().split())
        if student_norm and student_norm == ideal_norm:
            return GradeResult(
                accuracy_score=1.0,
                is_correct=True,
                feedback="Matches the ideal answer exactly.",
                reasoning="Exact match to the model answer after normalization.",
                error_category=ShortAnswerErrorCategory.NO_ERROR.value,
                missing_keywords=[],
                detailed_explanation="",
            )

        prompt = render(
            "grading/semantic_short_answer.jinja",
            question=payload.question,
            ideal_answer=payload.ideal_answer,
            keywords=", ".join(payload.keywords),
            student_answer=student_answer.strip(),
        )
        detected_missing = _keywords_missing(payload.keywords, student_norm)
        try:
            result = self._llm.generate_json(prompt, temperature=0.15)
        except Exception as exc:
            return GradeResult(
                accuracy_score=0.0,
                is_correct=False,
                feedback=f"Grading failed: {exc}",
                error_category=(
                    ShortAnswerErrorCategory.MISSING_KEYWORDS.value
                    if detected_missing
                    else ShortAnswerErrorCategory.COMPLETELY_IRRELEVANT.value
                ),
                missing_keywords=detected_missing,
                detailed_explanation="The semantic judge was unavailable, so the response could not be fully scored.",
            )
        raw_score = result.get("accuracy_score", result.get("score", 0.0))
        score = float(raw_score)
        score = max(0.0, min(1.0, score))

        keyword_hits = sum(
            1 for kw in payload.keywords
            if kw and kw.lower() in student_norm
        )
        if payload.keywords:
            keyword_ratio = keyword_hits / len(payload.keywords)
            if keyword_ratio >= 1.0:
                score = max(score, 0.9)
            elif keyword_ratio >= 0.75:
                score = max(score, 0.75)
            elif keyword_ratio >= 0.5:
                score = max(score, 0.55)

        llm_missing = result.get("missing_keywords") or []
        merged_missing: list[str] = []
        seen: set[str] = set()
        for item in list(llm_missing) + detected_missing:
            token = str(item).strip()
            key = token.lower()
            if token and key not in seen:
                seen.add(key)
                merged_missing.append(token)

        is_correct = score >= _PASS_THRESHOLD
        if is_correct:
            category = ShortAnswerErrorCategory.NO_ERROR.value
            merged_missing = []
            explanation = ""
        else:
            category = _parse_sa_category(result.get("error_category"), score=score, missing=merged_missing)
            explanation = _clamp_sentences(str(result.get("detailed_explanation") or ""), max_sentences=2)
            if not explanation:
                explanation = "The answer does not yet cover every required scientific idea."

        reasoning = str(result.get("reasoning", "")).strip()
        if not reasoning:
            reasoning = str(result.get("feedback", "")).strip()
        return GradeResult(
            accuracy_score=score,
            is_correct=is_correct,
            feedback=self._feedback_matches_outcome(str(result.get("feedback", "")), is_correct=is_correct),
            reasoning=reasoning,
            error_category=category,
            missing_keywords=merged_missing,
            detailed_explanation=explanation,
        )
