"""Helpers for turning raw attempt history into stable signals.

Kept separate from the policy itself so unit tests can exercise the maths
independently of action selection.
"""

from __future__ import annotations

from collections import Counter

from iae.core.models import AttemptRecord, QuestionType


def rolling_accuracy(history: list[AttemptRecord], window: int) -> float:
    """Mean accuracy over the most recent ``window`` attempts.

    Returns 0.0 when no attempts have been recorded yet so the policy treats
    the cold-start path as "no signal" rather than "perfect" or "failing".
    """
    if not history:
        return 0.0
    recent = history[-window:]
    return sum(a.accuracy_score for a in recent) / len(recent)


def current_streak(history: list[AttemptRecord]) -> int:
    streak = 0
    for attempt in reversed(history):
        if attempt.is_correct:
            streak += 1
        else:
            break
    return streak


def question_type_counts(history: list[AttemptRecord]) -> Counter[QuestionType]:
    return Counter(a.question_type for a in history)
