"""IRT-inspired chapter-level dynamic difficulty controller.

This is a transparent, rule-based DDA policy that uses Rasch-style proxy
signals (rolling accuracy and normalized response time) to target DOK levels.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from iae.core.models import AttemptRecord, QuestionType, RlAction, RlState
from iae.adaptive.telemetry import question_type_counts, rolling_accuracy

_QUESTION_TYPE_ROTATION: tuple[QuestionType, ...] = (
    QuestionType.MCQ,
    QuestionType.SHORT_ANSWER,
    QuestionType.MULTI_BLANK,
    QuestionType.TRUE_FALSE,
)


@dataclass(frozen=True)
class PolicyConfig:
    cold_start_dok: int
    rolling_window: int
    target_accuracy_lower: float
    target_accuracy_upper: float


class ConceptAwareNavigationPolicy:
    def __init__(self, config: PolicyConfig, *, rng: random.Random | None = None) -> None:
        self._config = config
        self._rng = rng or random.Random()

    def cold_start_action(self, scope_chapter: str) -> RlAction:
        return RlAction(
            target_chapter=scope_chapter,
            next_difficulty_level=self._config.cold_start_dok,
            next_question_type=QuestionType.MCQ,
            next_sub_concept="ChapterWide",
        )

    def next_action(self, state: RlState, history: list[AttemptRecord]) -> RlAction:
        accuracy = rolling_accuracy(history, self._config.rolling_window)
        next_dok = self._adjust_difficulty(
            current=state.current_difficulty,
            accuracy=accuracy,
            time_taken=state.time_taken,
        )
        next_type = self._choose_question_type(history)
        return RlAction(
            target_chapter=state.current_chapter,
            next_difficulty_level=next_dok,
            next_question_type=next_type,
            next_sub_concept="ChapterWide",
        )

    def _adjust_difficulty(self, *, current: int, accuracy: float, time_taken: float) -> int:
        # IRT-style proxy: when theta - b is low, ease difficulty.
        # theta is approximated by rolling accuracy and b by current DOK.
        theta = (accuracy - 0.5) * 2.0  # map [0,1] -> [-1,1]
        item_b = (current - 2.5) / 1.5  # map DOK 1..4 -> about [-1,1]
        gap = theta - item_b

        # Time-aware override: very slow responses indicate cognitive overload.
        if time_taken >= 0.85 and accuracy < self._config.target_accuracy_upper:
            return max(1, current - 1)

        if accuracy < self._config.target_accuracy_lower:
            return max(1, current - 1)
        if accuracy > self._config.target_accuracy_upper and time_taken <= 0.45 and gap > 0.20:
            return min(4, current + 1)
        return current

    def _choose_question_type(self, history: list[AttemptRecord]) -> QuestionType:
        counts = question_type_counts(history)
        ranked = sorted(_QUESTION_TYPE_ROTATION, key=lambda qt: counts.get(qt, 0))
        return ranked[0]

