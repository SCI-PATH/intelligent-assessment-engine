"""Multivariate next-item policy for post-lesson / customizable quizzes.

Does NOT compute BKT. Component 4 supplies mastery_probability / seen; this
policy combines those inputs with local Elo ability, previous item difficulty
(b), response time, question type performance, rolling accuracy, and streak.

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
W_RECENCY = 0.25  # penalty if topic just used
W_PREV_B = 0.40  # previous item difficulty vs ability
W_TIME = 0.30  # previous response-time pressure
W_ROLLING_ACC = 0.45  # last-k accuracy momentum
W_STREAK = 0.35  # consecutive correct (+) / wrong (-)
W_TYPE_ROTATION = 0.20  # prefer next type in rotation
W_TYPE_WEAKNESS = 0.50  # avoid formats the learner is failing

TARGET_TIME_S = 45.0
ROLLING_WINDOW = 5


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


def select_topic_id(
    *,
    chapter_ids: Sequence[str],
    bkt_snapshot: dict[str, Any] | None,
    recently_used_topics: Sequence[str] | None = None,
) -> tuple[str, float]:
    topics = _topics_from_snapshot(bkt_snapshot, chapter_ids)
    if not topics:
        return "", 0.0
    topic_bkt: dict[str, Any] = {}
    if isinstance(bkt_snapshot, dict) and isinstance(bkt_snapshot.get("topic_bkt"), dict):
        topic_bkt = bkt_snapshot["topic_bkt"]
    recent = {t for t in (recently_used_topics or []) if t}

    best_tid = topics[0]
    best_score = float("-inf")
    for tid in topics:
        row = topic_bkt.get(tid) if isinstance(topic_bkt.get(tid), dict) else {}
        try:
            mastery = float(row.get("mastery_probability", 0.5))
        except (TypeError, ValueError):
            mastery = 0.5
        seen = bool(row.get("seen", False))
        score = W_MASTERY_GAP * (1.0 - mastery)
        if not seen:
            score += W_UNSEEN
        if tid in recent:
            score -= W_RECENCY
        if score > best_score:
            best_score = score
            best_tid = tid
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
) -> MultivariateDecision:
    """Pick topic_id, dok_level, question_type from multivariate weighted signals."""
    types = list(allowed_question_types) or list(QuestionType)
    hist_ok = list(history_correct or [])
    hist_types = list(history_types or [])
    rolling = _rolling_accuracy(hist_ok)
    streak = compute_streak(hist_ok)

    topic_id, topic_score = select_topic_id(
        chapter_ids=chapter_ids,
        bkt_snapshot=bkt_snapshot,
        recently_used_topics=recently_used_topics,
    )

    # --- DOK from Elo + multivariate adjustments ---
    target_dok = elo_to_target_dok(elo_rating)
    signals: dict[str, float] = {
        "elo_rating": float(elo_rating),
        "topic_score": float(topic_score),
        "streak": float(streak),
        "rolling_accuracy": float(rolling) if rolling is not None else -1.0,
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
        # Slow answers (time_pressure < 1) pull difficulty down when also wrong
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

    # Map continuous delta into integer DOK step, clamp ±1 from previous
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
    signals["dok_delta"] = dok_delta
    signals["target_dok"] = float(target_dok)

    # --- Question type: rotation + weakness avoidance ---
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
        if previous_type in rotation:
            next_rot = rotation[(rotation.index(previous_type) + 1) % len(rotation)]
            if qtype == next_rot:
                score += W_TYPE_ROTATION
        elif qtype == QuestionType.MCQ:
            score += W_TYPE_ROTATION * 0.5
        fail = fail_rates.get(qtype, 0.0)
        score -= W_TYPE_WEAKNESS * fail
        # After slow wrong constructed-response, prefer recognition formats
        if (
            previous_correct is False
            and previous_response_time_s is not None
            and previous_response_time_s > TARGET_TIME_S
            and previous_type in (QuestionType.SHORT_ANSWER, QuestionType.MULTI_BLANK)
            and qtype in (QuestionType.MCQ, QuestionType.TRUE_FALSE)
        ):
            score += 0.4
        if score > best_type_score:
            best_type_score = score
            best_type = qtype
    signals["type_score"] = best_type_score

    reason = (
        f"topic={topic_id or 'chapter_wide'} dok={target_dok} type={best_type.value} "
        f"elo={elo_rating:.1f} streak={streak} dok_delta={dok_delta:.2f}"
    )
    return MultivariateDecision(
        topic_id=topic_id,
        dok_level=target_dok,
        question_type=best_type,
        elo_rating=elo_rating,
        reason=reason,
        signals=signals,
    )
