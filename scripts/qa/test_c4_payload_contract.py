"""C4 assessment-submit + BKT snapshot contract smoke (no live HTTP).

Asserts the unified payload keys/null matrix from
docs/COMPONENT2_COMPONENT4_INTEGRATION.md and that C4 paths are unchanged.
"""

from __future__ import annotations

import sys

from scripts._path import ensure_src_on_path

ensure_src_on_path()

from iae.application.analytics_payload import _CONTRACT_KEYS, build_analytics_payload
from iae.application.grading import GradingService, blanks_match
from iae.config.peers import C4_ASSESSMENT_SUBMIT_PATH, C4_BKT_SNAPSHOT_PATH
from iae.domain.models import (
    DistractorTag,
    GradeResult,
    MCQPayload,
    MultiBlankPayload,
    OptionDiagnostic,
    Question,
    QuestionOrigin,
    QuestionStatus,
    QuestionType,
    ShortAnswerPayload,
    TrueFalsePayload,
)


def _q(**kwargs) -> Question:
    defaults = dict(
        chapter_name="Magnets",
        sub_concept="Magnetic poles",
        dok_level=2,
        skill="poles",
        topic_id="G6_C7_MAG_POLES",
        status=QuestionStatus.APPROVED,
        origin=QuestionOrigin.AI,
        grade=6,
    )
    defaults.update(kwargs)
    return Question(**defaults)


def _assert_keys(payload: dict) -> None:
    for key in _CONTRACT_KEYS:
        assert key in payload, f"missing contract key {key}"


def main() -> int:
    assert C4_BKT_SNAPSHOT_PATH == "/api/v1/quiz/bkt-snapshot"
    assert C4_ASSESSMENT_SUBMIT_PATH == "/api/v1/assessment-submit"

    assert blanks_match("Energy", "energy")
    assert blanks_match("ENERGY", "energy")
    assert blanks_match("photosyntesis", "photosynthesis")
    assert not blanks_match("water", "later")
    assert not blanks_match("acid", "base")
    assert not blanks_match("iron", "icon")

    grader = GradingService(llm=None)  # type: ignore[arg-type]
    mb = _q(
        id="mb-1",
        question_type=QuestionType.MULTI_BLANK,
        payload=MultiBlankPayload(
            paragraph="Plants use [_____] and [_____] and [_____].",
            answers=["energy", "water", "photosynthesis"],
        ),
    )
    # Case + spelling on all three → conceptually all correct.
    mb_ok = grader.grade(mb, "Energy|WATER|photosyntesis")
    assert mb_ok.is_correct, mb_ok
    assert mb_ok.error_category == "NO_ERROR"
    assert not mb_ok.missed_blanks

    mb_part = grader.grade(mb, "energy|later|photosynthesis")
    assert not mb_part.is_correct
    assert mb_part.error_category == "PARTIAL_MASTERY"
    assert mb_part.missed_blanks == {"1": "water"}

    payload_mb = build_analytics_payload(
        user_id="student_001",
        question=mb,
        grade=mb_part,
        student_answer="energy|later|photosynthesis",
        response_time_s=12.0,
        chapter_ids=["G6_C7"],
    )
    _assert_keys(payload_mb)
    assert payload_mb["question_type"] == "MultiBlank"
    assert payload_mb["similarity_score"] == mb_part.accuracy_score
    assert payload_mb["distractor_tag"] is None
    assert payload_mb["distractor_label"] is None
    assert payload_mb["chosen_distractor_text"] is None
    assert payload_mb["detailed_explanation"] is None
    assert payload_mb["error_category"] == "PARTIAL_MASTERY"
    assert payload_mb["missed_blanks"] == {"1": "water"}
    assert payload_mb["source"] == "question_engine_v1"
    assert payload_mb["chapter_ids"] == ["G6_C7"]
    assert payload_mb["topic_id"] == "G6_C7_MAG_POLES"
    print("OK MultiBlank C4 matrix + spelling/case")

    mcq = _q(
        id="mcq-1",
        question_type=QuestionType.MCQ,
        payload=MCQPayload(
            question="Which is correct?",
            options={"A": "ok", "B": "wrong idea", "C": "x", "D": "y"},
            correct_answer="A",
            option_diagnostics={
                "B": OptionDiagnostic(
                    distractor_tag=DistractorTag.MISCONCEPTION,
                    distractor_label="The student incorrectly treats like poles as attracting.",
                )
            },
        ),
    )
    mcq_wrong = grader.grade(mcq, "B")
    p_mcq = build_analytics_payload(
        user_id="student_001",
        question=mcq,
        grade=mcq_wrong,
        student_answer="B",
        response_time_s=8.0,
        chapter_ids=["G6_C7"],
    )
    _assert_keys(p_mcq)
    assert p_mcq["similarity_score"] is None
    assert p_mcq["error_category"] is None
    assert p_mcq["missed_blanks"] is None
    assert p_mcq["distractor_tag"] == "MISCONCEPTION"
    assert p_mcq["distractor_label"]
    assert p_mcq["chosen_distractor_text"] == "wrong idea"
    print("OK MCQ C4 matrix")

    tf = _q(
        id="tf-1",
        question_type=QuestionType.TRUE_FALSE,
        payload=TrueFalsePayload(
            question="Unlike poles attract.",
            correct_answer="True",
            distractor_tag=DistractorTag.MISCONCEPTION,
            distractor_label="The student incorrectly believes like poles attract.",
        ),
    )
    tf_wrong = grader.grade(tf, "False")
    p_tf = build_analytics_payload(
        user_id="student_001",
        question=tf,
        grade=tf_wrong,
        student_answer="False",
        response_time_s=5.0,
    )
    _assert_keys(p_tf)
    assert p_tf["similarity_score"] is None
    assert p_tf["error_category"] is None
    assert p_tf["missed_blanks"] is None
    assert p_tf["distractor_tag"] == "MISCONCEPTION"
    assert p_tf["chosen_distractor_text"] == "False"
    assert p_tf["detailed_explanation"]
    print("OK TrueFalse C4 matrix")

    sa = _q(
        id="sa-1",
        question_type=QuestionType.SHORT_ANSWER,
        payload=ShortAnswerPayload(
            question="Explain.",
            ideal_answer="Plants use sunlight.",
            keywords=["sunlight", "plants", "energy"],
        ),
    )
    sa_grade = GradeResult(
        accuracy_score=0.45,
        is_correct=False,
        error_category="MISSING_KEYWORDS",
        detailed_explanation="The answer omitted sunlight.",
    )
    p_sa = build_analytics_payload(
        user_id="student_001",
        question=sa,
        grade=sa_grade,
        student_answer="something",
        response_time_s=20.0,
    )
    _assert_keys(p_sa)
    assert p_sa["similarity_score"] == 0.45
    assert p_sa["distractor_tag"] is None
    assert p_sa["missed_blanks"] is None
    assert p_sa["error_category"] == "MISSING_KEYWORDS"
    print("OK ShortAnswer C4 matrix")

    print("C4_CONTRACT_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print("FAIL", exc, file=sys.stderr)
        raise SystemExit(1) from exc
