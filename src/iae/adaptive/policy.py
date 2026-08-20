"""IRT-inspired chapter-level dynamic difficulty controller.

This is a transparent, rule-based DDA policy that uses Rasch-style proxy
signals (rolling accuracy and normalized response time) to target DOK levels.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

from iae.adaptive import rule_catalog as rc
from iae.adaptive.telemetry import question_type_counts, rolling_accuracy
from iae.core.models import AttemptRecord, QuestionType, RlAction, RlState, RuleTrace, TraceCondition

# Agent NDJSON writers removed from production paths.
def _debug_log(*, run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    return


_RAPID_GUESS_SECONDS = 1.5
_GRACE_HOLD_MAX_NORMALIZED_TIME = 1.15
# Policy thresholds shared by DOK and question-type branches
_LAST_WEAK_ACC = 0.50  # strictly below counts as weak (same as weak performance for types)
_LAST_STRONG_ACC = 0.85
_ROLL_UP = 0.80
_SLOW_SECONDS = 45.0
_FAST_UP_SECONDS = 30.0


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
        dok_trace = RuleTrace(
            rule_id=rc.RULE_DOK_R0_COLD_START.rule_id,
            title=rc.RULE_DOK_R0_COLD_START.title,
            category="cold_start",
            pedagogy_tag=rc.RULE_DOK_R0_COLD_START.pedagogy_tag,
            conditions=[
                TraceCondition(
                    label="No graded attempts in session yet",
                    met=True,
                    observed="—",
                ),
            ],
            outcome=f"THEN set DOK = {self._config.cold_start_dok} (configured cold_start_dok)",
        )
        type_trace = RuleTrace(
            rule_id=rc.RULE_TYPE_R0_COLD_START.rule_id,
            title=rc.RULE_TYPE_R0_COLD_START.title,
            category="cold_start",
            pedagogy_tag=rc.RULE_TYPE_R0_COLD_START.pedagogy_tag,
            conditions=[
                TraceCondition(label=rc.RULE_TYPE_R0_COLD_START.if_summary, met=True, observed="—"),
            ],
            outcome="THEN set type = MCQ",
        )
        dsum = f"{dok_trace.rule_id}: {dok_trace.outcome}"
        tsum = f"{type_trace.rule_id}: {type_trace.outcome}"
        return RlAction(
            target_chapter=scope_chapter,
            next_difficulty_level=self._config.cold_start_dok,
            next_question_type=QuestionType.MCQ,
            next_sub_concept="ChapterWide",
            rule_triggered=f"{dok_trace.rule_id}+{type_trace.rule_id}",
            dok_reason=dok_trace.rule_id,
            question_type_reason=type_trace.rule_id,
            dok_summary=dsum,
            type_summary=tsum,
            dok_trace=dok_trace,
            type_trace=type_trace,
            previous_response_time_seconds=0.0,
        )

    def next_action(self, state: RlState, history: list[AttemptRecord]) -> RlAction:
        rolling_acc = rolling_accuracy(history, self._config.rolling_window)
        consecutive_strong = self._tail_consecutive_strong(history)
        consecutive_weak = self._tail_consecutive_weak(history)
        (
            next_dok,
            rule_triggered,
            theta,
            item_b,
            rapid_guessing_detected,
            format_simplification_triggered,
            dok_trace,
        ) = self._adjust_difficulty(
            current=state.current_difficulty,
            rolling_accuracy=rolling_acc,
            last_accuracy=state.accuracy_score,
            time_taken=state.time_taken,
            response_time_seconds=state.response_time_seconds,
            streak=state.streak,
            consecutive_strong=consecutive_strong,
            consecutive_weak=consecutive_weak,
            last_question_type=state.last_question_type,
        )
        next_type, _type_rule_id, type_trace = self._choose_question_type(
            history=history,
            current_state=state,
            incoming_dok=next_dok,
            format_simplification_triggered=format_simplification_triggered,
        )
        dsum = f"{dok_trace.rule_id}: {dok_trace.outcome}"
        tsum = f"{type_trace.rule_id}: {type_trace.outcome}"
        return RlAction(
            target_chapter=state.current_chapter,
            next_difficulty_level=next_dok,
            next_question_type=next_type,
            next_sub_concept="ChapterWide",
            rule_triggered=f"{dok_trace.rule_id}+{type_trace.rule_id}",
            dok_reason=dok_trace.rule_id,
            question_type_reason=type_trace.rule_id,
            dok_summary=dsum,
            type_summary=tsum,
            dok_trace=dok_trace,
            type_trace=type_trace,
            estimated_theta=theta,
            item_b=item_b,
            previous_response_time_seconds=state.response_time_seconds,
            rapid_guessing_detected=rapid_guessing_detected,
            format_simplification_triggered=format_simplification_triggered,
        )

    def _adjust_difficulty(
        self,
        *,
        current: int,
        rolling_accuracy: float,
        last_accuracy: float,
        time_taken: float,
        response_time_seconds: float,
        streak: int,
        consecutive_strong: int,
        consecutive_weak: int,
        last_question_type: QuestionType | None,
    ) -> tuple[int, str, float, float, bool, bool, RuleTrace]:
        """Choose next DOK; returns structured ``RuleTrace`` for the UI/API."""

        # Rasch-style proxies:
        theta_roll = (rolling_accuracy - 0.5) * 2.0
        theta_last = (last_accuracy - 0.5) * 2.0

        speed_adj = 0.0
        if time_taken >= 0.85:
            speed_adj = -0.35
        elif time_taken <= 0.45:
            speed_adj = 0.25

        theta = 0.65 * theta_roll + 0.35 * theta_last + speed_adj
        item_b = (current - 2.5) / 1.5
        gap = theta - item_b

        # Rule priority:
        # 1) Increase (explicit signal of readiness)
        # 2a) High DOK protective downshift — one weak last answer at DOK 3–4
        # 2b) Lower DOK downshift — two weak answers in a row + low rolling average
        # 3) Hold

        weak_last = last_accuracy < _LAST_WEAK_ACC
        increase_ok = (
            rolling_accuracy >= _ROLL_UP
            and last_accuracy >= _LAST_STRONG_ACC
            and response_time_seconds <= _FAST_UP_SECONDS
        )
        decrease_high_dok = current >= 3 and weak_last
        decrease_low_dok = (
            current <= 2
            and consecutive_weak >= 2
            and rolling_accuracy < _LAST_WEAK_ACC
            and weak_last
        )

        _debug_log(
            run_id="pre-fix",
            hypothesis_id="H1",
            location="src/iae/adaptive/policy.py:_adjust_difficulty",
            message="Policy decision inputs and branch flags",
            data={
                "current_dok": current,
                "rolling_accuracy": round(rolling_accuracy, 4),
                "last_accuracy": round(last_accuracy, 4),
                "time_taken_normalized": round(time_taken, 4),
                "raw_response_seconds": round(response_time_seconds, 4),
                "rapid_guess_threshold_seconds": _RAPID_GUESS_SECONDS,
                "grace_hold_max_normalized_time": _GRACE_HOLD_MAX_NORMALIZED_TIME,
                "streak": streak,
                "consecutive_strong": consecutive_strong,
                "consecutive_weak": consecutive_weak,
                "theta": round(theta, 4),
                "item_b": round(item_b, 4),
                "gap": round(gap, 4),
                "weak_last": weak_last,
                "increase": increase_ok,
                "decrease_high_dok": decrease_high_dok,
                "decrease_low_dok": decrease_low_dok,
            },
        )
        if increase_ok:
            next_level = min(4, current + 1)
            e = rc.RULE_DOK_R1_PROGRESSION
            trace = RuleTrace(
                rule_id=e.rule_id,
                title=e.title,
                category="dok",
                pedagogy_tag=e.pedagogy_tag,
                conditions=[
                    TraceCondition(
                        label=f"Rolling average ≥ {_ROLL_UP:.0%}",
                        met=rolling_accuracy >= _ROLL_UP,
                        observed=f"{rolling_accuracy:.0%}",
                    ),
                    TraceCondition(
                        label=f"Last graded score ≥ {_LAST_STRONG_ACC:.0%}",
                        met=last_accuracy >= _LAST_STRONG_ACC,
                        observed=f"{last_accuracy:.0%}",
                    ),
                    TraceCondition(
                        label=f"Response time ≤ {_FAST_UP_SECONDS:.0f}s",
                        met=response_time_seconds <= _FAST_UP_SECONDS,
                        observed=f"{response_time_seconds:.1f}s",
                    ),
                    TraceCondition(
                        label="Diagnostic: correct-pass streak (is_correct)",
                        met=None,
                        observed=str(streak),
                    ),
                    TraceCondition(
                        label="Diagnostic: weak streak (score < 50%), tail",
                        met=None,
                        observed=str(consecutive_weak),
                    ),
                ],
                outcome=f"THEN DOK {current} → {next_level}",
            )
            return (next_level, "progression", theta, item_b, False, False, trace)

        if decrease_high_dok:
            next_level = max(1, current - 1)
            e = rc.RULE_DOK_R2_HIGH_PROTECT
            trace = RuleTrace(
                rule_id=e.rule_id,
                title=e.title,
                category="dok",
                pedagogy_tag=e.pedagogy_tag,
                conditions=[
                    TraceCondition(
                        label="Current DOK ∈ {3, 4}",
                        met=current >= 3,
                        observed=str(current),
                    ),
                    TraceCondition(
                        label=f"Last graded score < {_LAST_WEAK_ACC:.0%}",
                        met=weak_last,
                        observed=f"{last_accuracy:.0%}",
                    ),
                    TraceCondition(
                        label="Rolling average (context)",
                        met=None,
                        observed=f"{rolling_accuracy:.0%}",
                    ),
                    TraceCondition(
                        label="Response time (context)",
                        met=None,
                        observed=f"{response_time_seconds:.1f}s",
                    ),
                ],
                outcome=f"THEN DOK {current} → {next_level}",
            )
            return (next_level, "support downshift high dok", theta, item_b, False, False, trace)

        if decrease_low_dok:
            next_level = max(1, current - 1)
            e = rc.RULE_DOK_R3_LOW_SUSTAINED
            trace = RuleTrace(
                rule_id=e.rule_id,
                title=e.title,
                category="dok",
                pedagogy_tag=e.pedagogy_tag,
                conditions=[
                    TraceCondition(
                        label="Current DOK ∈ {1, 2}",
                        met=current <= 2,
                        observed=str(current),
                    ),
                    TraceCondition(
                        label="Weak streak ≥ 2 consecutive (score < 50%)",
                        met=consecutive_weak >= 2,
                        observed=str(consecutive_weak),
                    ),
                    TraceCondition(
                        label=f"Rolling average < {_LAST_WEAK_ACC:.0%}",
                        met=rolling_accuracy < _LAST_WEAK_ACC,
                        observed=f"{rolling_accuracy:.0%}",
                    ),
                    TraceCondition(
                        label=f"Last graded score < {_LAST_WEAK_ACC:.0%}",
                        met=weak_last,
                        observed=f"{last_accuracy:.0%}",
                    ),
                ],
                outcome=f"THEN DOK {current} → {next_level}",
            )
            return (next_level, "support downshift low dok", theta, item_b, False, False, trace)

        trace = _dok_trace_hold(
            current=current,
            rolling_accuracy=rolling_accuracy,
            last_accuracy=last_accuracy,
            response_time_seconds=response_time_seconds,
            streak=streak,
            consecutive_weak=consecutive_weak,
            weak_last=weak_last,
            increase_ok=increase_ok,
            decrease_high_dok=decrease_high_dok,
            decrease_low_dok=decrease_low_dok,
        )
        return (current, "stability", theta, item_b, False, False, trace)

    @staticmethod
    def _tail_consecutive_strong(history: list[AttemptRecord]) -> int:
        count = 0
        for attempt in reversed(history):
            if attempt.accuracy_score >= 0.85:
                count += 1
            else:
                break
        return count

    @staticmethod
    def _tail_consecutive_weak(history: list[AttemptRecord]) -> int:
        count = 0
        for attempt in reversed(history):
            if attempt.accuracy_score < _LAST_WEAK_ACC:
                count += 1
            else:
                break
        return count

    def _choose_question_type(
        self,
        *,
        history: list[AttemptRecord],
        current_state: RlState,
        incoming_dok: int,
        _format_simplification_triggered: bool,
    ) -> tuple[QuestionType, str, RuleTrace]:
        if not history:
            t = RuleTrace(
                rule_id=rc.RULE_TYPE_R0_COLD_START.rule_id,
                title=rc.RULE_TYPE_R0_COLD_START.title,
                category="cold_start",
                pedagogy_tag=rc.RULE_TYPE_R0_COLD_START.pedagogy_tag,
                conditions=[
                    TraceCondition(label=rc.RULE_TYPE_R0_COLD_START.if_summary, met=True, observed="—"),
                ],
                outcome="THEN type = MCQ",
            )
            return QuestionType.MCQ, t.rule_id, t

        rolling_acc = rolling_accuracy(history, self._config.rolling_window)
        acc = current_state.accuracy_score
        response_time_seconds = current_state.response_time_seconds
        counts = question_type_counts(history)

        str_counts = _summarize_type_counts(counts)

        # Strong path → expressive type (planned DOK from DOK branch)
        if acc >= _LAST_STRONG_ACC and rolling_acc >= _ROLL_UP:
            if incoming_dok >= 3:
                e = rc.RULE_TYPE_R1_MULTI_BLANK
                trace = RuleTrace(
                    rule_id=e.rule_id,
                    title=e.title,
                    category="type",
                    pedagogy_tag=e.pedagogy_tag,
                    conditions=[
                        TraceCondition(
                            label=f"Last graded score ≥ {_LAST_STRONG_ACC:.0%}",
                            met=acc >= _LAST_STRONG_ACC,
                            observed=f"{acc:.0%}",
                        ),
                        TraceCondition(
                            label=f"Rolling average ≥ {_ROLL_UP:.0%}",
                            met=rolling_acc >= _ROLL_UP,
                            observed=f"{rolling_acc:.0%}",
                        ),
                        TraceCondition(
                            label="Planned next DOK ≥ 3 (after DOK policy)",
                            met=incoming_dok >= 3,
                            observed=str(incoming_dok),
                        ),
                        TraceCondition(label="Session type counts (context)", met=None, observed=str_counts),
                    ],
                    outcome="THEN type = MultiBlank",
                )
                return QuestionType.MULTI_BLANK, trace.rule_id, trace

            e = rc.RULE_TYPE_R1_SHORT_ANSWER
            trace = RuleTrace(
                rule_id=e.rule_id,
                title=e.title,
                category="type",
                pedagogy_tag=e.pedagogy_tag,
                conditions=[
                    TraceCondition(
                        label=f"Last graded score ≥ {_LAST_STRONG_ACC:.0%}",
                        met=acc >= _LAST_STRONG_ACC,
                        observed=f"{acc:.0%}",
                    ),
                    TraceCondition(
                        label=f"Rolling average ≥ {_ROLL_UP:.0%}",
                        met=rolling_acc >= _ROLL_UP,
                        observed=f"{rolling_acc:.0%}",
                    ),
                    TraceCondition(
                        label="Planned next DOK < 3 (after DOK policy)",
                        met=incoming_dok < 3,
                        observed=str(incoming_dok),
                    ),
                    TraceCondition(label="Session type counts (context)", met=None, observed=str_counts),
                ],
                outcome="THEN type = ShortAnswer",
            )
            return QuestionType.SHORT_ANSWER, trace.rule_id, trace

        if acc < _LAST_WEAK_ACC:
            e = rc.RULE_TYPE_R2_WEAK
            trace = RuleTrace(
                rule_id=e.rule_id,
                title=e.title,
                category="type",
                pedagogy_tag=e.pedagogy_tag,
                conditions=[
                    TraceCondition(
                        label=f"Last graded score < {_LAST_WEAK_ACC:.0%}",
                        met=acc < _LAST_WEAK_ACC,
                        observed=f"{acc:.0%}",
                    ),
                    TraceCondition(label="Rolling average (context)", met=None, observed=f"{rolling_acc:.0%}"),
                    TraceCondition(
                        label="Response time (context)",
                        met=None,
                        observed=f"{response_time_seconds:.1f}s",
                    ),
                ],
                outcome="THEN type = MCQ",
            )
            return QuestionType.MCQ, trace.rule_id, trace

        if response_time_seconds > _SLOW_SECONDS:
            e = rc.RULE_TYPE_R3_SLOW
            trace = RuleTrace(
                rule_id=e.rule_id,
                title=e.title,
                category="type",
                pedagogy_tag=e.pedagogy_tag,
                conditions=[
                    TraceCondition(
                        label=f"Response time > {_SLOW_SECONDS:.0f}s",
                        met=response_time_seconds > _SLOW_SECONDS,
                        observed=f"{response_time_seconds:.1f}s",
                    ),
                    TraceCondition(label="Last graded score (context)", met=None, observed=f"{acc:.0%}"),
                    TraceCondition(label="Rolling average (context)", met=None, observed=f"{rolling_acc:.0%}"),
                ],
                outcome="THEN type = TrueFalse",
            )
            return QuestionType.TRUE_FALSE, trace.rule_id, trace

        candidates: tuple[QuestionType, ...] = (
            QuestionType.MCQ,
            QuestionType.TRUE_FALSE,
            QuestionType.MULTI_BLANK,
        )
        least = min(candidates, key=lambda t: counts.get(t, 0))
        ties = [t for t in candidates if counts.get(t, 0) == counts.get(least, 0)]
        chosen = self._rng.choice(ties) if len(ties) > 1 else least
        e = rc.RULE_TYPE_R4_LEAST_USED
        trace = RuleTrace(
            rule_id=e.rule_id,
            title=e.title,
            category="type",
            pedagogy_tag=e.pedagogy_tag,
            conditions=[
                TraceCondition(
                    label=f"Sustained strong path — last ≥{_LAST_STRONG_ACC:.0%} AND rolling ≥{_ROLL_UP:.0%}",
                    met=(acc >= _LAST_STRONG_ACC and rolling_acc >= _ROLL_UP),
                    observed=f"last={acc:.0%}, rolling={rolling_acc:.0%}",
                ),
                TraceCondition(
                    label=f"Recovery gate — last < {_LAST_WEAK_ACC:.0%} (would force MCQ)",
                    met=(acc < _LAST_WEAK_ACC),
                    observed=f"{acc:.0%}",
                ),
                TraceCondition(
                    label=f"Latency gate — time > {_SLOW_SECONDS:.0f}s (would force TrueFalse)",
                    met=(response_time_seconds > _SLOW_SECONDS),
                    observed=f"{response_time_seconds:.1f}s",
                ),
                TraceCondition(label="Among MCQ, TrueFalse, MultiBlank lowest count wins", met=True, observed=str_counts),
                TraceCondition(label="Chosen", met=True, observed=f"{chosen.value} (tie → random choice)"),
            ],
            outcome=f"THEN type = {chosen.value} (least-used rotation)",
        )
        return chosen, trace.rule_id, trace


def _dok_trace_hold(
    *,
    current: int,
    rolling_accuracy: float,
    last_accuracy: float,
    response_time_seconds: float,
    streak: int,
    consecutive_weak: int,
    weak_last: bool,
    increase_ok: bool,
    decrease_high_dok: bool,
    decrease_low_dok: bool,
) -> RuleTrace:
    """Full predicate grid so 'hold' is auditable."""

    entry = rc.RULE_DOK_R4_HOLD
    prog_block = TraceCondition(
        label=f"(Rule R1 trio) Progressive step-up fires only if ALL hold: rolling ≥{_ROLL_UP:.0%}",
        met=rolling_accuracy >= _ROLL_UP,
        observed=f"{rolling_accuracy:.0%}",
    )
    prog_last = TraceCondition(
        label=f"(Rule R1) … AND last graded score ≥{_LAST_STRONG_ACC:.0%}",
        met=last_accuracy >= _LAST_STRONG_ACC,
        observed=f"{last_accuracy:.0%}",
    )
    prog_time = TraceCondition(
        label=f"(Rule R1) … AND time ≤{_FAST_UP_SECONDS:.0f}s",
        met=response_time_seconds <= _FAST_UP_SECONDS,
        observed=f"{response_time_seconds:.1f}s",
    )
    prog_fused = TraceCondition(
        label="⇒ Progressive step-up (all three)",
        met=increase_ok,
        observed=str(increase_ok),
    )

    hd_dok = TraceCondition(
        label="(Rule R2 high-DOK) Current DOK ∈ {3,4}",
        met=current >= 3,
        observed=str(current),
    )
    hd_weak = TraceCondition(
        label=f"(Rule R2 …) Last < {_LAST_WEAK_ACC:.0%}",
        met=weak_last,
        observed=f"{last_accuracy:.0%}",
    )
    hd_fused = TraceCondition(
        label="⇒ High-DOK support down-shift",
        met=decrease_high_dok,
        observed=str(decrease_high_dok),
    )

    ld_dok = TraceCondition(label="(Rule R3 low-DOK) Current DOK ∈ {1,2}", met=current <= 2, observed=str(current))
    ld_ws = TraceCondition(
        label="(Rule R3 …) Weak streak ≥2",
        met=consecutive_weak >= 2,
        observed=str(consecutive_weak),
    )
    ld_roll = TraceCondition(
        label=f"(Rule R3 …) Rolling avg <{_LAST_WEAK_ACC:.0%}",
        met=rolling_accuracy < _LAST_WEAK_ACC,
        observed=f"{rolling_accuracy:.0%}",
    )
    ld_last = TraceCondition(
        label=f"(Rule R3 …) Last <{_LAST_WEAK_ACC:.0%}",
        met=weak_last,
        observed=f"{last_accuracy:.0%}",
    )
    ld_fused = TraceCondition(
        label="⇒ Low-DOK sustained down-shift",
        met=decrease_low_dok,
        observed=str(decrease_low_dok),
    )

    ctx = TraceCondition(label="Diagnostics: streak / weak tail", met=None, observed=f"pass_streak={streak},weak_tail={consecutive_weak}")

    return RuleTrace(
        rule_id=entry.rule_id,
        title=entry.title,
        category="dok",
        pedagogy_tag=entry.pedagogy_tag,
        conditions=[
            prog_block,
            prog_last,
            prog_time,
            prog_fused,
            hd_dok,
            hd_weak,
            hd_fused,
            ld_dok,
            ld_ws,
            ld_roll,
            ld_last,
            ld_fused,
            ctx,
        ],
        outcome=f"THEN DOK {current} → {current} (unchanged)",
    )


def _summarize_type_counts(counts: Counter[QuestionType]) -> str:
    parts = [f"{qt.value}×{counts[qt]}" for qt in QuestionType if counts.get(qt, 0)]
    return ", ".join(parts) if parts else "none yet"


