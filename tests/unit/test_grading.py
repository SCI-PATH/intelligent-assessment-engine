"""Unit tests for deterministic grading paths (no LLM / no DB)."""

from __future__ import annotations

from iae.application.grading import GradingService, blanks_match
from iae.domain.models import (
    DistractorTag,
    MCQPayload,
    MultiBlankPayload,
    OptionDiagnostic,
    Question,
    QuestionOrigin,
    QuestionStatus,
    QuestionType,
    TrueFalsePayload,
)

class FakeLlm:
    """Minimal ILlmJson stand-in (deterministic graders never call it)."""

    def generate_json(self, prompt: str, *, temperature: float = 0.3) -> dict:
        return {}


def _question(**kwargs) -> Question:
    defaults = dict(
        chapter_name="Matter",
        sub_concept="States of matter",
        dok_level=2,
        skill="states",
        topic_id="G6_C1_STATES",
        status=QuestionStatus.APPROVED,
        origin=QuestionOrigin.AI,
    )
    defaults.update(kwargs)
    return Question(**defaults)


def test_blanks_match_case_and_punctuation() -> None:
    assert blanks_match("Energy", "energy")
    assert blanks_match("kinetic-energy", "kinetic energy")
    assert blanks_match("photosyntesis", "photosynthesis")


def test_blanks_match_rejects_different_words() -> None:
    assert not blanks_match("water", "later")
    assert not blanks_match("iron", "icon")
    assert not blanks_match("sun", "son")


def test_grade_mcq_correct() -> None:
    q = _question(
        question_type=QuestionType.MCQ,
        payload=MCQPayload(
            question="Which is a solid?",
            options={"A": "Ice", "B": "Steam", "C": "Air", "D": "Fog"},
            correct_answer="A",
        ),
    )
    result = GradingService(FakeLlm()).grade(q, "a")
    assert result.is_correct is True
    assert result.accuracy_score == 1.0


def test_grade_mcq_wrong_uses_stored_diagnostics() -> None:
    q = _question(
        question_type=QuestionType.MCQ,
        payload=MCQPayload(
            question="Which is a solid?",
            options={"A": "Ice", "B": "Steam", "C": "Air", "D": "Fog"},
            correct_answer="A",
            option_diagnostics={
                "B": OptionDiagnostic(
                    distractor_tag=DistractorTag.NEAR_MISS,
                    distractor_label="Confused solid with gas form of water",
                )
            },
        ),
    )
    result = GradingService(FakeLlm()).grade(q, "B")
    assert result.is_correct is False
    assert result.distractor_tag == DistractorTag.NEAR_MISS.value
    assert "Confused solid" in (result.distractor_label or "")


def test_grade_true_false_correct_and_wrong() -> None:
    q = _question(
        question_type=QuestionType.TRUE_FALSE,
        payload=TrueFalsePayload(
            question="Ice is a solid.",
            correct_answer="True",
            distractor_tag=DistractorTag.MISCONCEPTION,
            distractor_label="Student treats ice as a liquid",
        ),
    )
    grader = GradingService(FakeLlm())
    ok = grader.grade(q, "true")
    assert ok.is_correct is True

    bad = grader.grade(q, "false")
    assert bad.is_correct is False
    assert bad.distractor_tag == DistractorTag.MISCONCEPTION.value


def test_grade_multi_blank_partial() -> None:
    q = _question(
        question_type=QuestionType.MULTI_BLANK,
        payload=MultiBlankPayload(
            paragraph="Matter can be a ___ or a ___.",
            answers=["solid", "liquid"],
        ),
    )
    result = GradingService(FakeLlm()).grade(q, "solid | gas")
    assert result.is_correct is False
    assert 0.0 < result.accuracy_score < 1.0
    assert result.missed_blanks is not None
