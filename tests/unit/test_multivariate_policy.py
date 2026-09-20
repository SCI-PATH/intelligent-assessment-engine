"""Unit tests for multivariate next-item policy helpers."""

from __future__ import annotations

from iae.adaptive.multivariate_policy import (
    compute_streak,
    is_dok_floor_stall,
    scaffold_triggered,
    select_next_item,
)
from iae.domain.models import QuestionType

_TOPIC_A = "G6_C8_ELE_CIRCUITS"
_TOPIC_B = "G6_C8_ELE_CONDINS"


def _snapshot_two_topics(*, mastery_a: float, mastery_b: float) -> dict:
    return {
        "topic_ids": [_TOPIC_A, _TOPIC_B],
        "topics_by_chapter": {"G6_C8": [_TOPIC_A, _TOPIC_B]},
        "topic_bkt": {
            _TOPIC_A: {
                "mastery_probability": mastery_a,
                "mastery_category": "intermediate" if mastery_a >= 0.5 else "basic",
                "attempts": 5,
                "seen": True,
            },
            _TOPIC_B: {
                "mastery_probability": mastery_b,
                "mastery_category": "intermediate" if mastery_b >= 0.5 else "basic",
                "attempts": 0,
                "seen": False,
            },
        },
    }


def test_compute_streak_empty() -> None:
    assert compute_streak([]) == 0


def test_compute_streak_correct_run() -> None:
    assert compute_streak([False, True, True, True]) == 3


def test_compute_streak_wrong_run() -> None:
    assert compute_streak([True, False, False]) == -2


def test_compute_streak_single() -> None:
    assert compute_streak([True]) == 1
    assert compute_streak([False]) == -1


def test_scaffold_triggered_on_wrong_short_answer() -> None:
    assert scaffold_triggered(
        previous_correct=False,
        previous_type=QuestionType.SHORT_ANSWER,
    )
    assert not scaffold_triggered(
        previous_correct=True,
        previous_type=QuestionType.SHORT_ANSWER,
    )
    assert not scaffold_triggered(
        previous_correct=False,
        previous_type=QuestionType.MCQ,
    )


def test_is_dok_floor_stall() -> None:
    assert is_dok_floor_stall(
        streak=-2,
        last_item_dok=1,
        previous_type=QuestionType.MCQ,
    )
    assert not is_dok_floor_stall(
        streak=-2,
        last_item_dok=2,
        previous_type=QuestionType.MCQ,
    )
    assert not is_dok_floor_stall(
        streak=-2,
        last_item_dok=1,
        previous_type=QuestionType.SHORT_ANSWER,
    )


def test_scaffold_holds_dok_and_lowers_format() -> None:
    decision = select_next_item(
        elo_rating=1100.0,
        chapter_ids=["G6_C8"],
        bkt_snapshot=_snapshot_two_topics(mastery_a=0.4, mastery_b=0.7),
        allowed_question_types=list(QuestionType),
        previous_type=QuestionType.SHORT_ANSWER,
        last_item_dok=3,
        previous_correct=False,
        previous_response_time_s=60.0,
        history_correct=[False],
        history_types=[QuestionType.SHORT_ANSWER],
    )
    assert decision.dok_level == 3
    assert decision.question_type in (QuestionType.MCQ, QuestionType.TRUE_FALSE)
    assert decision.signals.get("scaffold") == 1.0


def test_dok_floor_stall_reallocates_topic() -> None:
    # Stuck on TOPIC_A at DOK 1 → must pick a different topic (mastery-gap reallocation).
    decision = select_next_item(
        elo_rating=900.0,
        chapter_ids=["G6_C8"],
        bkt_snapshot=_snapshot_two_topics(mastery_a=0.2, mastery_b=0.35),
        allowed_question_types=list(QuestionType),
        previous_type=QuestionType.MCQ,
        last_item_dok=1,
        previous_correct=False,
        previous_response_time_s=40.0,
        recently_used_topics=[_TOPIC_A],
        history_correct=[False, False],
        history_types=[QuestionType.MCQ, QuestionType.MCQ],
        last_topic_id=_TOPIC_A,
    )
    assert decision.signals.get("dok_floor_stall") == 1.0
    assert decision.topic_id != _TOPIC_A
    assert decision.topic_id == _TOPIC_B


def test_r_eff_low_mastery_pulls_dok_down() -> None:
    high_snap = {
        "topic_ids": [_TOPIC_A],
        "topics_by_chapter": {"G6_C8": [_TOPIC_A]},
        "topic_bkt": {
            _TOPIC_A: {
                "mastery_probability": 0.95,
                "mastery_category": "advanced",
                "attempts": 10,
                "seen": True,
            },
        },
    }
    low_snap = {
        "topic_ids": [_TOPIC_A],
        "topics_by_chapter": {"G6_C8": [_TOPIC_A]},
        "topic_bkt": {
            _TOPIC_A: {
                "mastery_probability": 0.1,
                "mastery_category": "basic",
                "attempts": 2,
                "seen": True,
            },
        },
    }
    high = select_next_item(
        elo_rating=1200.0,
        chapter_ids=["G6_C8"],
        bkt_snapshot=high_snap,
        allowed_question_types=[QuestionType.MCQ],
    )
    low = select_next_item(
        elo_rating=1200.0,
        chapter_ids=["G6_C8"],
        bkt_snapshot=low_snap,
        allowed_question_types=[QuestionType.MCQ],
    )
    assert low.signals["r_eff"] < high.signals["r_eff"]
    assert low.dok_level <= high.dok_level
