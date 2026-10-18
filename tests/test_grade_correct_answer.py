"""GradeResult always carries the bank key. Groq must not be asked to invent it."""

from iae.application.grading import GradingService, engine_correct_answer
from iae.domain.models import (
    DistractorTag,
    MCQPayload,
    MultiBlankPayload,
    Question,
    QuestionType,
    ShortAnswerPayload,
    TrueFalsePayload,
)


class _NoLlm:
    def generate_json(self, *_args, **_kwargs):
        raise RuntimeError("LLM must not be used to decide the correct answer")


def _question(question_type, payload, **extra):
    return Question(
        chapter_name="Plants",
        sub_concept="reproduction",
        dok_level=1,
        question_type=question_type,
        payload=payload,
        **extra,
    )


def test_mcq_grade_returns_bank_option_not_student_choice():
    q = _question(
        QuestionType.MCQ,
        MCQPayload(
            question="How do flowering plants reproduce?",
            options={
                "A": "By stems only",
                "B": "By seeds",
                "C": "By water transport",
                "D": "By branching",
            },
            correct_answer="B",
        ),
    )
    graded = GradingService(_NoLlm()).grade(q, "A")
    assert graded.is_correct is False
    assert graded.correct_answer == "B — By seeds"
    assert "stem" not in (graded.correct_answer or "").lower()


def test_true_false_grade_returns_bank_polarity():
    q = _question(
        QuestionType.TRUE_FALSE,
        TrueFalsePayload(
            question="Flowering plants produce seeds.",
            correct_answer="True",
            distractor_tag=DistractorTag.MISCONCEPTION,
            distractor_label="Polarity reversed",
        ),
    )
    graded = GradingService(_NoLlm()).grade(q, "False")
    assert graded.correct_answer == "True"


def test_fill_in_grade_returns_all_bank_blanks():
    q = _question(
        QuestionType.MULTI_BLANK,
        MultiBlankPayload(
            paragraph="Flowering plants produce ___ that grow into ___.",
            answers=["seeds", "new plants"],
        ),
    )
    graded = GradingService(_NoLlm()).grade(q, "stems | water")
    assert graded.correct_answer == "seeds | new plants"
    assert graded.accepted_answers == ["seeds", "new plants"]


def test_correct_mcq_letter_option_text_and_wrong_choice():
    q = _question(
        QuestionType.MCQ,
        MCQPayload(
            question="Which process makes food in a leaf?",
            options={
                "A": "Respiration",
                "B": "Photosynthesis",
                "C": "Transpiration",
                "D": "Germination",
            },
            correct_answer="B",
        ),
    )
    grader = GradingService(_NoLlm())
    assert grader.grade(q, "B").is_correct is True
    assert grader.grade(q, "b").is_correct is True
    assert grader.grade(q, "  Photosynthesis ").is_correct is True
    assert grader.grade(q, "B — Photosynthesis").is_correct is True
    wrong = grader.grade(q, "A")
    assert wrong.is_correct is False
    assert grader.grade(q, "Respiration").is_correct is False
    assert grader.grade(q, "photo").is_correct is False


def test_true_false_accepts_only_the_real_polarity():
    q = _question(
        QuestionType.TRUE_FALSE,
        TrueFalsePayload(
            question="Leaves make food.",
            correct_answer="True",
            distractor_tag=DistractorTag.MISCONCEPTION,
            distractor_label="Polarity reversed",
        ),
    )
    grader = GradingService(_NoLlm())
    assert grader.grade(q, " True ").is_correct is True
    assert grader.grade(q, "true.").is_correct is True
    assert grader.grade(q, "False").is_correct is False
    assert grader.grade(q, "transpiration").is_correct is False


def test_short_answer_accepts_case_and_whitespace_not_a_different_idea():
    q = _question(
        QuestionType.SHORT_ANSWER,
        ShortAnswerPayload(
            question="Name the process plants use to make food.",
            ideal_answer="Photosynthesis",
            keywords=["photosynthesis", "food", "light"],
        ),
    )
    grader = GradingService(_NoLlm())
    assert grader.grade(q, " photosynthesis ").is_correct is True
    assert grader.grade(q, "PHOTOSYNTHESIS.").is_correct is True
    assert grader.grade(q, "respiration").is_correct is False


def test_short_answer_numbers_match_without_a_tolerance_guess():
    q = _question(
        QuestionType.SHORT_ANSWER,
        ShortAnswerPayload(
            question="How many cotyledons does a bean seed have?",
            ideal_answer="2",
            keywords=["two", "cotyledon", "bean"],
        ),
    )
    grader = GradingService(_NoLlm())
    assert grader.grade(q, "2.0").is_correct is True
    assert grader.grade(q, "2 kg").is_correct is False
    assert grader.grade(q, "3").is_correct is False


def test_multi_blank_keeps_commas_and_collapses_space():
    q = _question(
        QuestionType.MULTI_BLANK,
        MultiBlankPayload(
            paragraph="Plants need ___ and ___.",
            answers=["carbon dioxide", "new plants"],
        ),
    )
    grader = GradingService(_NoLlm())
    graded = grader.grade(q, " Carbon dioxide | New  plants ")
    assert graded.is_correct is True
    missed = grader.grade(q, "oxygen | new plants")
    assert missed.is_correct is False
    assert missed.correct_answer == "carbon dioxide | new plants"


def test_short_answer_grade_returns_ideal_answer_without_llm_guessing():
    q = _question(
        QuestionType.SHORT_ANSWER,
        ShortAnswerPayload(
            question="What is the role of seeds in flowering plants?",
            ideal_answer="They grow into new plants",
            keywords=["seeds", "new plants"],
        ),
    )
    graded = GradingService(_NoLlm()).grade(q, "stems carry water")
    assert graded.correct_answer == "They grow into new plants"
    assert graded.ideal_answer == "They grow into new plants"
    assert engine_correct_answer(q) == "They grow into new plants"
