"""Amplitude Test: weighted heuristic initial categorization (no BKT).

Research algorithm
------------------
Inputs
  - Historical block (40% of weighted score by default):
      past marks band, chapters completed (normalized), study hours, self-confidence
  - Fixed 10-item quiz (60%): quiz_correct / quiz_total

Categories
  - BASIC         weighted_score < 0.45
  - INTERMEDIATE  0.45 <= weighted_score <= 0.75
  - ADVANCED      weighted_score > 0.75

The 10 quiz items are grade-stable (same question_ids for every student)
so cohorts remain comparable for research.
"""

from __future__ import annotations

from iae.domain.models import AmplitudeCategory, PastGradeMarksRange

_PAST_SCORE = {
    PastGradeMarksRange.BELOW_50: 0.25,
    PastGradeMarksRange.BAND_50_75: 0.625,
    PastGradeMarksRange.ABOVE_75: 0.875,
}


def history_composite_score(
    *,
    past_grade_marks_range: PastGradeMarksRange,
    completed_chapters_count: int,
    study_hours_per_week: float | None = None,
    self_confidence: int | None = None,
    expected_chapters: int = 12,
) -> float:
    """Blend four historical signals into [0, 1]."""
    marks = _PAST_SCORE[past_grade_marks_range]
    chapter_ratio = min(max(completed_chapters_count / max(1, expected_chapters), 0.0), 1.0)
    hours = 0.5
    if study_hours_per_week is not None:
        # 0–14h/week mapped into [0, 1]
        hours = min(max(float(study_hours_per_week) / 14.0, 0.0), 1.0)
    confidence = 0.5
    if self_confidence is not None:
        confidence = min(max(int(self_confidence), 1), 5) / 5.0
    return round(0.40 * marks + 0.30 * chapter_ratio + 0.15 * hours + 0.15 * confidence, 4)


def categorize(weighted_score: float) -> AmplitudeCategory:
    if weighted_score < 0.45:
        return AmplitudeCategory.BASIC
    if weighted_score <= 0.75:
        return AmplitudeCategory.INTERMEDIATE
    return AmplitudeCategory.ADVANCED


def weighted_amplitude_score(
    *,
    quiz_score: float,
    history_score: float,
    quiz_weight: float = 0.60,
    history_weight: float = 0.40,
) -> float:
    return round((quiz_weight * quiz_score) + (history_weight * history_score), 4)
