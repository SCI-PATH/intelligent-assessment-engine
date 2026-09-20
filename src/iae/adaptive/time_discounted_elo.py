"""Time-Discounted Elo DDA for adaptive quiz item selection.

Research notes
--------------
Student ability is tracked as an Elo rating ``R`` (start 1000).
Each item has difficulty ``b`` derived from DOK level::

    b = 800 + (dok - 1) * 200   # DOK1≈800 … DOK4≈1400

After an attempt with correctness ``s`` in {0,1} and response time ``t``
seconds (target ``T``)::

    expected = 1 / (1 + 10 ** ((b - R) / 400))
    time_factor = clip(T / max(t, 1), 0.5, 1.5)   # slow answers dampen update
    delta = K * time_factor * (s - expected)
    R <- R + delta

Next DOK is chosen so item difficulty sits near the student's rating
(target ~80% success), with gentle steps of at most ±1 DOK.
"""

from __future__ import annotations

from dataclasses import dataclass

from iae.domain.models import QuestionType


def dok_to_elo(dok: int) -> float:
    dok = max(1, min(4, int(dok)))
    return 800.0 + (dok - 1) * 200.0


def elo_to_target_dok(rating: float) -> int:
    raw = 1 + (rating - 800.0) / 200.0
    return max(1, min(4, int(round(raw))))


@dataclass
class EloUpdate:
    previous_rating: float
    new_rating: float
    expected: float
    time_factor: float
    delta: float
    next_dok: int
    next_question_type: QuestionType


def update_elo(
    *,
    rating: float,
    item_dok: int,
    is_correct: bool,
    response_time_s: float,
    target_time_s: float = 45.0,
    k_factor: float = 32.0,
    previous_type: QuestionType | None = None,
) -> EloUpdate:
    b = dok_to_elo(item_dok)
    expected = 1.0 / (1.0 + 10 ** ((b - rating) / 400.0))
    t = max(float(response_time_s), 1.0)
    time_factor = min(max(target_time_s / t, 0.5), 1.5)
    score = 1.0 if is_correct else 0.0
    delta = k_factor * time_factor * (score - expected)
    new_rating = rating + delta

    target = elo_to_target_dok(new_rating)
    if target > item_dok + 1:
        target = item_dok + 1
    elif target < item_dok - 1:
        target = item_dok - 1

    rotation = [
        QuestionType.MCQ,
        QuestionType.TRUE_FALSE,
        QuestionType.MULTI_BLANK,
        QuestionType.SHORT_ANSWER,
    ]
    if previous_type in rotation:
        idx = (rotation.index(previous_type) + 1) % len(rotation)
        next_type = rotation[idx]
    else:
        next_type = QuestionType.MCQ

    return EloUpdate(
        previous_rating=rating,
        new_rating=new_rating,
        expected=expected,
        time_factor=time_factor,
        delta=delta,
        next_dok=target,
        next_question_type=next_type,
    )
