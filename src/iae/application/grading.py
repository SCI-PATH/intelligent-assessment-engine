"""Grading pipeline: deterministic for structural items, LLM-judged for prose.

The service is intentionally tiny. It owns the routing decision and the
deterministic comparators; the LLM call delegates to ``ILlmJson`` and a
prompt asset, so nothing about the grading "personality" leaks into code.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from uuid import uuid4

from iae.core.models import (
    GradeResult,
    MultiBlankPayload,
    Question,
    QuestionType,
    ShortAnswerPayload,
)
from iae.core.protocols import ILlmJson
from iae.prompts import render

_PASS_THRESHOLD = 0.8
_DEBUG_LOG_PATH = Path("debug-21ced4.log")


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


class GradingService:
    """Implements ``IGradingService``."""

    def __init__(self, llm: ILlmJson) -> None:
        self._llm = llm

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
        return GradeResult(
            accuracy_score=1.0 if is_correct else 0.0,
            is_correct=is_correct,
            feedback="Correct." if is_correct else f"Incorrect. The right answer is {correct}.",
        )

    def _grade_true_false(self, question: Question, student_answer: str) -> GradeResult:
        correct = question.payload.correct_answer.strip().lower()
        chosen = student_answer.strip().lower()
        is_correct = chosen.startswith(correct[0])  # accepts T/True, F/False, etc.
        # #region agent log
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
        # #endregion
        return GradeResult(
            accuracy_score=1.0 if is_correct else 0.0,
            is_correct=is_correct,
            feedback="Correct." if is_correct else f"Incorrect. The statement is {correct.title()}.",
        )

    def _grade_multi_blank(self, question: Question, student_answer: str) -> GradeResult:
        payload: MultiBlankPayload = question.payload  # type: ignore[assignment]
        student_blanks = self._parse_blanks(student_answer, expected=len(payload.answers))
        ideal = [a.strip().lower() for a in payload.answers]
        provided = [b.strip().lower() for b in student_blanks]
        # Pad shorter responses so the per-blank index stays aligned.
        provided += [""] * (len(ideal) - len(provided))
        hits = sum(1 for given, expected in zip(provided, ideal) if given == expected)
        score = hits / len(ideal)
        return GradeResult(
            accuracy_score=score,
            is_correct=score >= _PASS_THRESHOLD,
            feedback=f"{hits} of {len(ideal)} blanks correct.",
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
            )

        # Deterministic shortcut: an exact (normalized) match against the ideal
        # answer is always 100%. This avoids LLM judges chronically capping at
        # 0.85 even for perfect responses.
        student_norm = " ".join(student_answer.lower().split())
        ideal_norm = " ".join(payload.ideal_answer.lower().split())
        if student_norm and student_norm == ideal_norm:
            return GradeResult(
                accuracy_score=1.0,
                is_correct=True,
                feedback="Matches the ideal answer exactly.",
                reasoning="Exact match to the model answer after normalization.",
            )

        prompt = render(
            "grading/semantic_short_answer.jinja",
            question=payload.question,
            ideal_answer=payload.ideal_answer,
            keywords=", ".join(payload.keywords),
            student_answer=student_answer.strip(),
        )
        try:
            result = self._llm.generate_json(prompt, temperature=0.15)
        except Exception as exc:  # pragma: no cover - surfaced to the caller
            return GradeResult(
                accuracy_score=0.0,
                is_correct=False,
                feedback=f"Grading failed: {exc}",
            )
        raw_score = result.get("accuracy_score", result.get("score", 0.0))
        score = float(raw_score)
        score = max(0.0, min(1.0, score))

        # Keyword sanity floor: if the student covered every required keyword,
        # do not score below 0.9. The LLM judge tends to under-score even
        # well-formed answers; this protects clearly-correct responses.
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

        is_correct = score >= _PASS_THRESHOLD
        reasoning = str(result.get("reasoning", "")).strip()
        if not reasoning:
            reasoning = str(result.get("feedback", "")).strip()
        return GradeResult(
            accuracy_score=score,
            is_correct=is_correct,
            feedback=self._feedback_matches_outcome(str(result.get("feedback", "")), is_correct=is_correct),
            reasoning=reasoning,
        )

