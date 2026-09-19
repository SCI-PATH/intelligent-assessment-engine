"""Unit tests for Time-Discounted Elo DDA helpers."""

from __future__ import annotations

from iae.adaptive.time_discounted_elo import dok_to_elo, elo_to_target_dok, update_elo
from iae.domain.models import QuestionType


def test_dok_to_elo_bounds() -> None:
    assert dok_to_elo(1) == 800.0
    assert dok_to_elo(2) == 1000.0
    assert dok_to_elo(3) == 1200.0
    assert dok_to_elo(4) == 1400.0
    assert dok_to_elo(0) == 800.0
    assert dok_to_elo(99) == 1400.0


def test_elo_to_target_dok() -> None:
    assert elo_to_target_dok(800.0) == 1
    assert elo_to_target_dok(1000.0) == 2
    assert elo_to_target_dok(1200.0) == 3
    assert elo_to_target_dok(1400.0) == 4


def test_update_elo_correct_raises_rating() -> None:
    result = update_elo(
        rating=1000.0,
        item_dok=2,
        is_correct=True,
        response_time_s=45.0,
        previous_type=QuestionType.MCQ,
    )
    assert result.new_rating > result.previous_rating
    assert result.delta > 0
    assert result.time_factor == 1.0
    assert result.next_question_type == QuestionType.TRUE_FALSE
    assert abs(result.next_dok - 2) <= 1


def test_update_elo_incorrect_lowers_rating() -> None:
    result = update_elo(
        rating=1000.0,
        item_dok=2,
        is_correct=False,
        response_time_s=45.0,
        previous_type=QuestionType.TRUE_FALSE,
    )
    assert result.new_rating < result.previous_rating
    assert result.delta < 0
    assert result.next_question_type == QuestionType.MULTI_BLANK


def test_update_elo_slow_answer_damps_delta() -> None:
    fast = update_elo(
        rating=1000.0,
        item_dok=2,
        is_correct=True,
        response_time_s=10.0,
    )
    slow = update_elo(
        rating=1000.0,
        item_dok=2,
        is_correct=True,
        response_time_s=120.0,
    )
    assert fast.time_factor > slow.time_factor
    assert abs(fast.delta) > abs(slow.delta)


def test_update_elo_dok_step_at_most_one() -> None:
    # Very high rating after easy correct should still only step +1 DOK.
    result = update_elo(
        rating=1600.0,
        item_dok=1,
        is_correct=True,
        response_time_s=20.0,
    )
    assert result.next_dok == 2
