"""Multivariate next-item policy for post-lesson / customizable quizzes.

Process (three axes — plain language)
-------------------------------------
Does NOT compute BKT. Component 4 supplies mastery_probability / seen /
attempts; this policy combines those with local session Elo to pick:

1. **Topic** — prefer weak skills (mastery gap = 1 − P(L)). Soft bonus for
   unseen / zero-attempt topics. If the learner is stuck at DOK 1 on easy
   formats (DOK-floor stall), **reallocate** to a different topic via the
   same mastery-gap score. Do **not** call this "frustration" — that word
   belongs to another component's affect/engagement signal.

2. **DOK (hardness 1–4)** — blend session Elo with the chosen topic's P(L)
   into R_eff, map to DOK, then nudge with time/streak/residuals. Step at
   most ±1 from the last item.

3. **Question type (format)** — cognitive scaffolding: if the learner fails
   a high-load format (Short Answer / MultiBlank), **hold DOK** and serve a
   lower-load format (MCQ / TrueFalse) before dropping content difficulty.

Session ``elo_rating`` stays the value returned on /next and /answer.
R_eff is selection-only (internal). Ability is never sent to C4.

Viva-visible weights (tune here only):
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from iae.adaptive.time_discounted_elo import dok_to_elo, elo_to_target_dok
from iae.domain.chapter_catalog import get_chapter, load_chapters
from iae.domain.models import QuestionType

# --- Named weights (presentation / panel) ---
W_MASTERY_GAP = 1.00  # prefer low P(L)
W_UNSEEN = 0.35  # bonus for unseen topics
W_ZERO_ATTEMPTS = 0.15  # soft coverage bonus when attempts == 0
W_RECENCY = 0.25  # penalty if topic just used
W_PREV_B = 0.40  # previous item difficulty vs ability
W_TIME = 0.30  # previous response-time pressure
W_ROLLING_ACC = 0.45  # last-k accuracy momentum
W_STREAK = 0.35  # consecutive correct (+) / wrong (-)
W_TYPE_ROTATION = 0.20  # prefer next type in rotation
W_TYPE_WEAKNESS = 0.50  # avoid formats the learner is failing
W_SCAFFOLD = 1.20  # strong preference for lower-load format after fail
# Blend for topic-conditioned DOK: R_eff = (1 - w)*R + w*topic_proxy
W_TOPIC_BLEND = 0.40

TARGET_TIME_S = 45.0
ROLLING_WINDOW = 5

# Format load bands for scaffolding (high → low response demand).
_HIGH_LOAD = frozenset({QuestionType.SHORT_ANSWER, QuestionType.MULTI_BLANK})
_LOW_LOAD = frozenset({QuestionType.MCQ, QuestionType.TRUE_FALSE})


@dataclass(frozen=True)
class MultivariateDecision:
    topic_id: str
    dok_level: int
    question_type: QuestionType
    elo_rating: float
    reason: str
    signals: dict[str, float]


def _catalog_topics_for_chapters(chapter_ids: Sequence[str]) -> list[str]:
    topics: list[str] = []
    catalog = load_chapters()
    for cid in chapter_ids:
        record = catalog.get(cid) or get_chapter(cid)
        if record is None:
            continue
        for tid in record.topic_ids:
            if tid and tid not in topics:
                topics.append(tid)
    return topics


def _topics_from_snapshot(bkt_snapshot: dict[str, Any] | None, chapter_ids: Sequence[str]) -> list[str]:
    catalog_topics = _catalog_topics_for_chapters(chapter_ids)
    catalog_set = set(catalog_topics)
    if not isinstance(bkt_snapshot, dict):
        return catalog_topics
    candidates: list[str] = []
    topics_by_chapter = bkt_snapshot.get("topics_by_chapter")
    if isinstance(topics_by_chapter, dict):
        for cid in chapter_ids:
            rows = topics_by_chapter.get(cid) or topics_by_chapter.get(str(cid)) or []
            if isinstance(rows, list):
                for tid in rows:
                    t = str(tid).strip()
                    if t and t in catalog_set and t not in candidates:
                        candidates.append(t)
    topic_ids = bkt_snapshot.get("topic_ids")
    if isinstance(topic_ids, list):
        for tid in topic_ids:
            t = str(tid).strip()
            if t and t in catalog_set and t not in candidates:
                candidates.append(t)
    topic_bkt = bkt_snapshot.get("topic_bkt")
    if isinstance(topic_bkt, dict):
        for tid in topic_bkt:
            t = str(tid).strip()
            if t and t in catalog_set and t not in candidates:
                candidates.append(t)
    return candidates or catalog_topics


def compute_streak(history_correct: Sequence[bool]) -> int:
    """Positive = consecutive corrects from end; negative = consecutive wrongs."""
    if not history_correct:
        return 0
    last = history_correct[-1]
    streak = 0
    for flag in reversed(history_correct):
        if flag == last:
            streak += 1
        else:
            break
    return streak if last else -streak


def _rolling_accuracy(history_correct: Sequence[bool], window: int = ROLLING_WINDOW) -> float | None:
    if not history_correct:
        return None
    slice_ = list(history_correct[-window:])
    return sum(1 for x in slice_ if x) / len(slice_)


def _type_failure_rates(
    history_types: Sequence[QuestionType],
    history_correct: Sequence[bool],
) -> dict[QuestionType, float]:
    totals: dict[QuestionType, int] = {}
    fails: dict[QuestionType, int] = {}
    for qtype, ok in zip(history_types, history_correct):
        totals[qtype] = totals.get(qtype, 0) + 1
        if not ok:
            fails[qtype] = fails.get(qtype, 0) + 1
    return {t: fails.get(t, 0) / n for t, n in totals.items() if n > 0}


def _topic_mastery(topic_bkt: dict[str, Any], topic_id: str) -> float:
    row = topic_bkt.get(topic_id) if isinstance(topic_bkt.get(topic_id), dict) else {}
    try:
        return float(row.get("mastery_probability", 0.5))
    except (TypeError, ValueError):
        return 0.5


def _topic_proxy_rating(mastery: float) -> float:
    """Map P(L) onto the same 800–1400 scale used for Elo seeding."""
    return 800.0 + 600.0 * max(0.0, min(1.0, float(mastery)))


def is_dok_floor_stall(
    *,
    streak: int,
    last_item_dok: int | None,
    previous_type: QuestionType | None,
) -> bool:
    """True when stuck at lowest DOK on recognition formats (topic reallocation).

    Naming: dok_floor_stall / mastery_gap_reallocation — not "frustration"
    (reserved for another component).
    """
    return (
        streak <= -2
        and last_item_dok == 1
        and previous_type in _LOW_LOAD
    )


def scaffold_triggered(
    *,
    previous_correct: bool | None,
    previous_type: QuestionType | None,
) -> bool:
    """Hold DOK and drop format load after a fail on constructed-response."""
    return previous_correct is False and previous_type in _HIGH_LOAD


def select_topic_id(
    *,
    chapter_ids: Sequence[str],
    bkt_snapshot: dict[str, Any] | None,
    recently_used_topics: Sequence[str] | None = None,
    exclude_topic_id: str | None = None,
) -> tuple[str, float]:
    """Pick topic with highest mastery-gap score; optionally force a different id."""
    topics = _topics_from_snapshot(bkt_snapshot, chapter_ids)
    if not topics:
        return "", 0.0
    topic_bkt: dict[str, Any] = {}
    if isinstance(bkt_snapshot, dict) and isinstance(bkt_snapshot.get("topic_bkt"), dict):
        topic_bkt = bkt_snapshot["topic_bkt"]
    recent = {t for t in (recently_used_topics or []) if t}
    exclude = (exclude_topic_id or "").strip()

    best_tid = ""
    best_score = float("-inf")
    for tid in topics:
        if exclude and tid == exclude:
            continue
        row = topic_bkt.get(tid) if isinstance(topic_bkt.get(tid), dict) else {}
        mastery = _topic_mastery(topic_bkt, tid)
        seen = bool(row.get("seen", False))
        try:
            attempts = int(row.get("attempts", 0) or 0)
        except (TypeError, ValueError):
            attempts = 0
        score = W_MASTERY_GAP * (1.0 - mastery)
        if not seen:
            score += W_UNSEEN
        if attempts == 0:
            score += W_ZERO_ATTEMPTS
        if tid in recent:
            score -= W_RECENCY
        if score > best_score:
            best_score = score
            best_tid = tid

    # If exclusion wiped the list, fall back to best including excluded.
    if not best_tid:
        return select_topic_id(
            chapter_ids=chapter_ids,
            bkt_snapshot=bkt_snapshot,
            recently_used_topics=recently_used_topics,
            exclude_topic_id=None,
        )
    return best_tid, best_score


def select_next_item(
    *,
    elo_rating: float,
    chapter_ids: Sequence[str],
    bkt_snapshot: dict[str, Any] | None,
    allowed_question_types: Sequence[QuestionType],
    previous_type: QuestionType | None = None,
    last_item_dok: int | None = None,
    previous_correct: bool | None = None,
    previous_response_time_s: float | None = None,
    recently_used_topics: Sequence[str] | None = None,
    history_correct: Sequence[bool] | None = None,
    history_types: Sequence[QuestionType] | None = None,
    last_topic_id: str | None = None,
) -> MultivariateDecision:
    """Pick topic_id, dok_level, question_type from multivariate weighted signals."""
    types = list(allowed_question_types) or list(QuestionType)
    hist_ok = list(history_correct or [])
    hist_types = list(history_types or [])
    rolling = _rolling_accuracy(hist_ok)
    streak = compute_streak(hist_ok)

    topic_bkt: dict[str, Any] = {}
    if isinstance(bkt_snapshot, dict) and isinstance(bkt_snapshot.get("topic_bkt"), dict):
        topic_bkt = bkt_snapshot["topic_bkt"]

    # --- Axis 1: topic (mastery gap; DOK-floor stall → reallocate) ---
    floor_stall = is_dok_floor_stall(
        streak=streak,
        last_item_dok=last_item_dok,
        previous_type=previous_type,
    )
    exclude = (last_topic_id or "").strip() or None
    if floor_stall and exclude:
        topic_id, topic_score = select_topic_id(
            chapter_ids=chapter_ids,
            bkt_snapshot=bkt_snapshot,
            recently_used_topics=recently_used_topics,
            exclude_topic_id=exclude,
        )
    else:
        topic_id, topic_score = select_topic_id(
            chapter_ids=chapter_ids,
            bkt_snapshot=bkt_snapshot,
            recently_used_topics=recently_used_topics,
        )

    # --- Axis 2: DOK from R_eff (session Elo blended with topic P(L)) ---
    mastery = _topic_mastery(topic_bkt, topic_id) if topic_id else 0.5
    topic_proxy = _topic_proxy_rating(mastery)
    r_eff = (1.0 - W_TOPIC_BLEND) * float(elo_rating) + W_TOPIC_BLEND * topic_proxy
    target_dok = elo_to_target_dok(r_eff)

    signals: dict[str, float] = {
        "elo_rating": float(elo_rating),
        "r_eff": float(r_eff),
        "topic_mastery": float(mastery),
        "topic_score": float(topic_score),
        "streak": float(streak),
        "rolling_accuracy": float(rolling) if rolling is not None else -1.0,
        "dok_floor_stall": 1.0 if floor_stall else 0.0,
    }

    dok_delta = 0.0
    if last_item_dok is not None:
        b_prev = dok_to_elo(last_item_dok)
        expected = 1.0 / (1.0 + 10 ** ((b_prev - elo_rating) / 400.0))
        signals["previous_b"] = b_prev
        signals["expected_success"] = expected
        if previous_correct is not None:
            # Underperform vs expected → easier; overperform → harder
            residual = (1.0 if previous_correct else 0.0) - expected
            dok_delta += W_PREV_B * residual

    if previous_response_time_s is not None and previous_response_time_s > 0:
        time_pressure = TARGET_TIME_S / max(float(previous_response_time_s), 1.0)
        time_pressure = min(max(time_pressure, 0.5), 1.5)
        signals["time_pressure"] = time_pressure
        if previous_correct is False and time_pressure < 1.0:
            dok_delta -= W_TIME * (1.0 - time_pressure)
        elif previous_correct is True and time_pressure > 1.0:
            dok_delta += W_TIME * (time_pressure - 1.0) * 0.5

    if rolling is not None:
        dok_delta += W_ROLLING_ACC * (rolling - 0.65)

    if streak >= 2:
        dok_delta += W_STREAK * min(streak, 4) / 4.0
    elif streak <= -2:
        dok_delta -= W_STREAK * min(-streak, 4) / 4.0

    if dok_delta > 0.25:
        target_dok = min(4, target_dok + 1)
    elif dok_delta < -0.25:
        target_dok = max(1, target_dok - 1)

    if last_item_dok is not None:
        if target_dok > last_item_dok + 1:
            target_dok = last_item_dok + 1
        elif target_dok < last_item_dok - 1:
            target_dok = last_item_dok - 1
    target_dok = max(1, min(4, int(target_dok)))

    # --- Axis 3: question type (scaffolding holds DOK) ---
    do_scaffold = scaffold_triggered(
        previous_correct=previous_correct,
        previous_type=previous_type,
    )
    if do_scaffold and last_item_dok is not None:
        # Cognitive scaffolding: same depth, lower format load.
        target_dok = int(last_item_dok)

    signals["dok_delta"] = dok_delta
    signals["target_dok"] = float(target_dok)
    signals["scaffold"] = 1.0 if do_scaffold else 0.0

    rotation = [
        QuestionType.MCQ,
        QuestionType.TRUE_FALSE,
        QuestionType.MULTI_BLANK,
        QuestionType.SHORT_ANSWER,
    ]
    fail_rates = _type_failure_rates(hist_types, hist_ok)
    best_type = types[0]
    best_type_score = float("-inf")
    for qtype in types:
        score = 0.0
        if do_scaffold:
            if qtype == QuestionType.MCQ:
                score += W_SCAFFOLD
            elif qtype == QuestionType.TRUE_FALSE:
                score += W_SCAFFOLD * 0.85
            elif qtype in _HIGH_LOAD:
                score -= W_SCAFFOLD
        else:
            if previous_type in rotation:
                next_rot = rotation[(rotation.index(previous_type) + 1) % len(rotation)]
                if qtype == next_rot:
                    score += W_TYPE_ROTATION
            elif qtype == QuestionType.MCQ:
                score += W_TYPE_ROTATION * 0.5
        fail = fail_rates.get(qtype, 0.0)
        score -= W_TYPE_WEAKNESS * fail
        # Secondary: slow wrong on constructed-response → recognition formats
        if (
            not do_scaffold
            and previous_correct is False
            and previous_response_time_s is not None
            and previous_response_time_s > TARGET_TIME_S
            and previous_type in _HIGH_LOAD
            and qtype in _LOW_LOAD
        ):
            score += 0.4
        if score > best_type_score:
            best_type_score = score
            best_type = qtype
    signals["type_score"] = best_type_score

    reason_parts = [
        f"topic={topic_id or 'chapter_wide'}",
        f"dok={target_dok}",
        f"type={best_type.value}",
        f"elo={elo_rating:.1f}",
        f"r_eff={r_eff:.1f}",
        f"streak={streak}",
        f"dok_delta={dok_delta:.2f}",
    ]
    if floor_stall:
        reason_parts.append("dok_floor_stall=1")
    if do_scaffold:
        reason_parts.append("scaffold=1")
    reason = " ".join(reason_parts)

    return MultivariateDecision(
        topic_id=topic_id,
        dok_level=target_dok,
        question_type=best_type,
        elo_rating=elo_rating,
        reason=reason,
        signals=signals,
    )
