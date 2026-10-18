"""Grading pipeline: deterministic for structural items, LLM-judged for prose.

Every question type attaches diagnostic fields on ``GradeResult`` so attempts
and analytics_events can persist them.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from iae.domain.models import (
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
from iae.domain.protocols import IEmbedder, ILlmJson
from iae.prompts import render

_PASS_THRESHOLD = 0.8
_SA_CATEGORIES = {item.value for item in ShortAnswerErrorCategory}
_SEMANTIC_GRADE_TIMEOUT_S = 14.0
_MCQ_LETTER = re.compile(r"^[A-D]$")
_MCQ_LETTER_PREFIX = re.compile(r"^([A-D])\s*[:.)\-—–]\s+", re.IGNORECASE)
_PLAIN_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_BLANK_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_BLANK_SPACE_RE = re.compile(r"[\s_\-/]+")


def _normalize_blank(text: str) -> str:
    """Case-fold, strip punctuation, collapse hyphens/underscores to spaces."""
    folded = (text or "").casefold().strip()
    folded = _BLANK_SPACE_RE.sub(" ", folded)
    folded = _BLANK_PUNCT_RE.sub("", folded)
    return " ".join(folded.split())


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(
                min(
                    cur[j - 1] + 1,
                    prev[j] + 1,
                    prev[j - 1] + (0 if ca == cb else 1),
                )
            )
        prev = cur
    return prev[-1]


def blanks_match(student: str, expected: str) -> bool:
    """True when a MultiBlank token is conceptually the same answer.

    - Capitalisation is ignored (``Energy`` == ``energy``).
    - Tiny spelling slips on longer words are accepted (``photosyntesis``).
    - Different science words are not accepted (``water`` ≠ ``later``).
    C4 MultiBlank ``error_category`` stays NO_ERROR | PARTIAL_MASTERY | FULL_MISCONCEPTION.
    """
    a = _normalize_blank(student)
    b = _normalize_blank(expected)
    if not b:
        return not a
    if a == b:
        return True
    # Short tokens: exact only after normalize (avoids iron/icon, sun/son).
    if min(len(a), len(b)) < 5:
        return False
    if a[0] != b[0] or a[-1] != b[-1]:
        return False
    allowed = 1 if max(len(a), len(b)) <= 8 else 2
    return _levenshtein(a, b) <= allowed


def collapse_answer_text(value: object) -> str:
    """Case-fold and collapse whitespace. Punctuation inside the answer stays."""
    return " ".join(str(value or "").strip().lower().split())


def text_answer_key(value: object) -> str:
    """Exact-match key: collapsed text, surrounding quotes removed, one trailing period."""
    text = collapse_answer_text(value).strip("\"'`")
    if text.endswith(".") and not _PLAIN_NUMBER.fullmatch(text[:-1] or ""):
        text = text[:-1].rstrip()
    return text


def answers_match_text(student: object, expected: object) -> bool:
    """True for the same text, or the same plain number (6 and 6.0). Not a fuzzy match."""
    left = text_answer_key(student)
    right = text_answer_key(expected)
    if left and left == right:
        return True
    if _PLAIN_NUMBER.fullmatch(left or "") and _PLAIN_NUMBER.fullmatch(right or ""):
        return abs(float(left) - float(right)) < 1e-9
    return False


def mcq_choice_letter(raw: object, options: dict | None = None) -> str:
    """Resolve a stored key or a submitted choice to A–D. Option text maps to its letter."""
    text = str(raw or "").strip()
    if not text:
        return ""
    upper = text.upper()
    if _MCQ_LETTER.fullmatch(upper):
        return upper
    prefixed = _MCQ_LETTER_PREFIX.match(text)
    if prefixed:
        return prefixed.group(1).upper()
    folded = collapse_answer_text(text)
    for letter, option_text in (options or {}).items():
        key = str(letter).strip().upper()
        if _MCQ_LETTER.fullmatch(key) and collapse_answer_text(option_text) == folded:
            return key
    return ""


def true_false_token(raw: object) -> str:
    text = text_answer_key(raw)
    if text in {"t", "true"}:
        return "true"
    if text in {"f", "false"}:
        return "false"
    return ""


def _keyword_fallback_grade(
    payload: ShortAnswerPayload,
    student_norm: str,
    detected_missing: list[str],
    *,
    reason: str,
) -> GradeResult:
    keyword_hits = sum(
        1 for kw in payload.keywords if kw and kw.lower() in student_norm
    )
    score = 0.0
    if payload.keywords:
        keyword_ratio = keyword_hits / len(payload.keywords)
        if keyword_ratio >= 1.0:
            score = 0.9
        elif keyword_ratio >= 0.75:
            score = 0.75
        elif keyword_ratio >= 0.5:
            score = 0.55
    is_correct = score >= _PASS_THRESHOLD
    return GradeResult(
        accuracy_score=score,
        is_correct=is_correct,
        feedback=(
            "Correct. The response meets the expected understanding."
            if is_correct
            else (
                "We could not fully score this answer right now. "
                "Try again in a moment, or check the lesson key idea."
            )
        ),
        error_category=(
            ShortAnswerErrorCategory.NO_ERROR.value
            if is_correct
            else (
                ShortAnswerErrorCategory.MISSING_KEYWORDS.value
                if detected_missing
                else ShortAnswerErrorCategory.COMPLETELY_IRRELEVANT.value
            )
        ),
        missing_keywords=[] if is_correct else detected_missing,
        detailed_explanation="" if is_correct else reason,
        ideal_answer=payload.ideal_answer,
    )


def _debug_log(*, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    return


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


def engine_correct_answer(question: Question) -> str:
    """Exact bank key for this question. Never inferred from the student response."""
    payload = question.payload
    if question.question_type == QuestionType.MCQ:
        letter = str(payload.correct_answer or "").strip().upper()
        options = getattr(payload, "options", None) or {}
        text = ""
        if isinstance(options, dict):
            text = str(options.get(letter) or options.get(letter.lower()) or "").strip()
        if letter and text:
            return f"{letter} — {text}"
        return letter
    if question.question_type == QuestionType.TRUE_FALSE:
        return str(payload.correct_answer or "").strip()
    if question.question_type == QuestionType.MULTI_BLANK:
        answers = [str(item).strip() for item in (payload.answers or []) if str(item).strip()]
        return " | ".join(answers)
    if question.question_type == QuestionType.SHORT_ANSWER:
        return str(getattr(payload, "ideal_answer", "") or "").strip()
    return ""


def engine_accepted_answers(question: Question) -> list[str] | None:
    if question.question_type == QuestionType.MULTI_BLANK:
        answers = [str(item).strip() for item in (question.payload.answers or []) if str(item).strip()]
        return answers or None
    key = engine_correct_answer(question)
    return [key] if key else None


def attach_engine_correct_answer(question: Question, result: GradeResult) -> GradeResult:
    key = engine_correct_answer(question)
    accepted = engine_accepted_answers(question)
    if key:
        result.correct_answer = key
    if accepted:
        result.accepted_answers = accepted
    if question.question_type == QuestionType.SHORT_ANSWER and not result.ideal_answer:
        result.ideal_answer = key or None
    return result


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
            result = self._grade_mcq(question, student_answer)
        elif question.question_type == QuestionType.TRUE_FALSE:
            result = self._grade_true_false(question, student_answer)
        elif question.question_type == QuestionType.MULTI_BLANK:
            result = self._grade_multi_blank(question, student_answer)
        else:
            result = self._grade_short_answer(question, student_answer)
        return attach_engine_correct_answer(question, result)

    # ---- deterministic graders -------------------------------------------------

    def _grade_mcq(self, question: Question, student_answer: str) -> GradeResult:
        options = getattr(question.payload, "options", None) or {}
        correct = mcq_choice_letter(question.payload.correct_answer, options)
        chosen = mcq_choice_letter(student_answer, options)
        is_correct = bool(correct) and chosen == correct
        result = GradeResult(
            accuracy_score=1.0 if is_correct else 0.0,
            is_correct=is_correct,
            feedback="Correct." if is_correct else f"Incorrect. The right answer is {correct}.",
        )
        if is_correct:
            return result

        # Prefer generation-time diagnostics stored on the bank payload (no LLM).
        payload = question.payload  # type: ignore[assignment]
        stored = getattr(payload, "option_diagnostics", None) or {}
        entry = stored.get(chosen) if isinstance(stored, dict) else None
        if entry is not None:
            tag_val = entry.distractor_tag if hasattr(entry, "distractor_tag") else entry.get("distractor_tag")
            label_val = entry.distractor_label if hasattr(entry, "distractor_label") else entry.get("distractor_label")
            if tag_val is not None and label_val:
                tag = tag_val if isinstance(tag_val, DistractorTag) else DistractorTag(str(tag_val))
                result.distractor_tag = tag.value
                result.distractor_label = str(label_val).strip()
                return result

        # Legacy rows without option_diagnostics: deterministic labels only on the
        # quiz hot path (no embedder / Groq). Keeps MCQ grading a string match.
        chosen_text = ""
        correct_text = ""
        try:
            chosen_text = str((payload.options or {}).get(chosen) or chosen).strip()
            correct_text = str((payload.options or {}).get(correct) or correct).strip()
        except Exception:
            chosen_text = chosen
            correct_text = correct
        result.distractor_tag = DistractorTag.COMPLETE_MISS.value
        result.distractor_label = (
            f"The student selected '{chosen_text}' rather than '{correct_text}', "
            f"indicating a complete miss of the target concept."
        )
        return result

    def _grade_true_false(self, question: Question, student_answer: str) -> GradeResult:
        payload: TrueFalsePayload = question.payload  # type: ignore[assignment]
        correct = true_false_token(payload.correct_answer)
        chosen = true_false_token(student_answer)
        is_correct = bool(correct) and chosen == correct
        if is_correct:
            return GradeResult(
                accuracy_score=1.0,
                is_correct=True,
                feedback="Correct.",
            )

        # Prefer generation-time distractor_tag / distractor_label on the payload.
        if payload.distractor_tag and payload.distractor_label:
            tag = (
                payload.distractor_tag
                if isinstance(payload.distractor_tag, DistractorTag)
                else DistractorTag(str(payload.distractor_tag))
            )
            explanation = f"The statement is {payload.correct_answer}."
            return GradeResult(
                accuracy_score=0.0,
                is_correct=False,
                feedback=f"Incorrect. The statement is {payload.correct_answer}.",
                distractor_tag=tag.value,
                distractor_label=str(payload.distractor_label).strip(),
                detailed_explanation=explanation,
                concept_explanation=explanation,
            )

        # Hot-path fallback: no Groq. ShortAnswer / offline regen still use LLM helpers.
        chosen_display = student_answer.strip() or "blank"
        correct_display = payload.correct_answer.strip()
        explanation = f"The statement is {correct_display}."
        return GradeResult(
            accuracy_score=0.0,
            is_correct=False,
            feedback=f"Incorrect. The statement is {correct_display}.",
            distractor_tag=DistractorTag.MISCONCEPTION.value,
            distractor_label=(
                f"The student selected {chosen_display} instead of {correct_display} "
                f"for the science claim being tested."
            ),
            detailed_explanation=explanation,
            concept_explanation=explanation,
        )

    def _true_false_diagnostics(
        self,
        payload: TrueFalsePayload,
        *,
        student_answer: str,
    ) -> tuple[DistractorTag, str, str]:
        """Return (tag, distractor_label, concept_explanation) for a wrong True/False."""
        chosen = student_answer.strip()
        correct = payload.correct_answer.strip()
        fallback_explanation = f"The statement is {correct}."
        if not chosen or chosen.lower()[0] not in ("t", "f"):
            return (
                DistractorTag.COMPLETE_MISS,
                "Gave an invalid or blank True/False response",
                fallback_explanation,
            )

        fallback_tag = DistractorTag.MISCONCEPTION
        fallback_label = f"Selected {chosen.title()} instead of {correct}"
        prompt = render(
            "grading/true_false_concept.jinja",
            question=payload.question,
            correct_answer=correct,
            student_answer=chosen,
        )
        try:
            result = self._llm.generate_json(prompt, temperature=0.15)
            raw_tag = str(result.get("distractor_tag") or "").strip().upper()
            try:
                tag = DistractorTag(raw_tag)
            except ValueError:
                tag = fallback_tag
            label = _clamp_sentences(str(result.get("distractor_label") or ""), max_sentences=1)
            # Prefer a short phrase: strip trailing period and keep roughly one clause.
            label = (label or fallback_label).rstrip(".")
            explanation = _clamp_sentences(str(result.get("concept_explanation") or ""), max_sentences=1)
            return tag, label or fallback_label, explanation or fallback_explanation
        except Exception:
            return fallback_tag, fallback_label, fallback_explanation

    def _grade_multi_blank(self, question: Question, student_answer: str) -> GradeResult:
        payload: MultiBlankPayload = question.payload  # type: ignore[assignment]
        student_blanks = self._parse_blanks(student_answer, expected=len(payload.answers))
        ideal = [a.strip() for a in payload.answers]
        provided = [b.strip() for b in student_blanks]
        provided += [""] * (len(ideal) - len(provided))
        hits = sum(1 for given, expected in zip(provided, ideal) if blanks_match(given, expected))
        score = hits / len(ideal) if ideal else 0.0
        missed_blanks = {
            str(index): payload.answers[index]
            for index, (given, expected) in enumerate(zip(provided, ideal))
            if not blanks_match(given, expected)
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
            feedback=(
                "Correct."
                if score >= _PASS_THRESHOLD
                else f"Incorrect. The blanks are: {' | '.join(payload.answers)}."
            ),
            error_category=category,
            missed_blanks=missed_blanks or None,
            detailed_explanation=(
                None
                if score >= _PASS_THRESHOLD
                else f"Expected blanks: {' | '.join(payload.answers)}."
            ),
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
        # Split only on the blank delimiter. Commas belong inside an answer.
        if "|" in raw:
            return [part.strip() for part in raw.split("|")][:expected]
        return [raw][:expected]

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
                feedback=(
                    "No answer was typed yet — write a short science idea and try again."
                ),
                reasoning="The response is blank, so no concept evidence could be evaluated.",
                error_category=ShortAnswerErrorCategory.COMPLETELY_IRRELEVANT.value,
                missing_keywords=list(payload.keywords or []),
                detailed_explanation="No answer was provided, so none of the required concepts were demonstrated.",
                ideal_answer=payload.ideal_answer,
            )

        student_norm = collapse_answer_text(student_answer)
        detected_missing = _keywords_missing(payload.keywords, student_norm)
        if answers_match_text(student_answer, payload.ideal_answer):
            return GradeResult(
                accuracy_score=1.0,
                is_correct=True,
                feedback="Matches the ideal answer exactly.",
                reasoning="Exact match to the model answer after normalization.",
                error_category=ShortAnswerErrorCategory.NO_ERROR.value,
                missing_keywords=[],
                detailed_explanation="",
                ideal_answer=payload.ideal_answer,
            )

        prompt = render(
            "grading/semantic_short_answer.jinja",
            question=payload.question,
            ideal_answer=payload.ideal_answer,
            keywords=", ".join(payload.keywords),
            student_answer=student_answer.strip(),
        )
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    self._llm.generate_json, prompt, temperature=0.15
                )
                result = future.result(timeout=_SEMANTIC_GRADE_TIMEOUT_S)
        except Exception as exc:
            # Never leak raw provider/model JSON into student-facing feedback.
            print(f"[iae] semantic grading unavailable: {exc}")
            return _keyword_fallback_grade(
                payload,
                student_norm,
                detected_missing,
                reason="The semantic judge was unavailable, so the response could not be fully scored.",
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
            ideal_answer=payload.ideal_answer,
        )
