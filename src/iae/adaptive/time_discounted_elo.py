"""Time-Discounted Elo — session ability update for Component 2 DDA.

Process (plain language)
------------------------
Component 2 keeps an internal ability number ``R`` (Elo) for *this quiz
session only*. It answers: "how hard should the next item be?" ``R`` is
**never** sent to Component 4; C4 only receives the graded attempt payload.

Seeding (quiz start, see ``quiz_service._elo_from_bkt_snapshot``)
----------------------------------------------------------------
When C4's BKT snapshot has topic mastery probabilities P(L)::

    R0 = 800 + 600 * mean(P(L))   # P(L)=0 → 800, P(L)=1 → 1400

``1000`` is only a **fallback** when no usable mastery rows exist
(cold start / C4 down). We do **not** ignore C4 when data is present.

Project calibration (not a universal Elo law)
---------------------------------------------
Item difficulty on the same scale as ``R``::

    b = 800 + (dok - 1) * 200   # DOK1≈800 … DOK4≈1400

After an attempt with correctness ``s`` in {0,1} and response time ``t``
seconds (target ``T``)::

    expected = 1 / (1 + 10 ** ((b - R) / 400))
    time_factor = clip(T / max(t, 1), 0.5, 1.5)
    delta = K * time_factor * (s - expected)
    R <- R + delta

Time-factor meaning
-------------------
- Fast correct  → larger boost  (fluent success)
- Slow correct  → smaller boost (success with struggle)
- Fast wrong    → larger drop   (rapid guess / confident error)
- Slow wrong    → smaller drop  (effortful fail)

This module updates ``R`` and proposes a base next DOK (±1 from the item).
**Question type** is owned by ``multivariate_policy`` (cognitive scaffolding).
``next_question_type`` here is legacy/compat only — the quiz path uses policy.
"""

from __future__ import annotations

from dataclasses import dataclass

from iae.domain.models import QuestionType


def dok_to_elo(dok: int) -> float:
    """Map Webb DOK 1–4 onto the project Elo difficulty scale."""
    dok = max(1, min(4, int(dok)))
    return 800.0 + (dok - 1) * 200.0


def elo_to_target_dok(rating: float) -> int:
    """Map ability rating back to a DOK band (nearest of 1–4)."""
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
    # Legacy hint only — multivariate_policy chooses the served type.
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
    """Update session ability R with time-weighted Elo; propose next DOK.

    Does not choose the next question format — that is policy-owned
    (scaffold same DOK to an easier format before dropping DOK).
    """
    b = dok_to_elo(item_dok)
    expected = 1.0 / (1.0 + 10 ** ((b - rating) / 400.0))
    t = max(float(response_time_s), 1.0)
    # phi > 1 when faster than target; phi < 1 when slower.
    time_factor = min(max(target_time_s / t, 0.5), 1.5)
    score = 1.0 if is_correct else 0.0
    delta = k_factor * time_factor * (score - expected)
    new_rating = rating + delta

    target = elo_to_target_dok(new_rating)
    if target > item_dok + 1:
        target = item_dok + 1
    elif target < item_dok - 1:
        target = item_dok - 1

    # Compat rotation only; quiz serving uses multivariate_policy for type.
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
