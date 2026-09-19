"""Unit tests for multivariate next-item policy helpers."""

from __future__ import annotations

from iae.adaptive.multivariate_policy import compute_streak


def test_compute_streak_empty() -> None:
    assert compute_streak([]) == 0


def test_compute_streak_correct_run() -> None:
    assert compute_streak([False, True, True, True]) == 3


def test_compute_streak_wrong_run() -> None:
    assert compute_streak([True, False, False]) == -2


def test_compute_streak_single() -> None:
    assert compute_streak([True]) == 1
    assert compute_streak([False]) == -1
