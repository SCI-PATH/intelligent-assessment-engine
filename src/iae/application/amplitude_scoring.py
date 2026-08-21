"""Amplitude Test: weighted heuristic initial categorization (no BKT).

Research algorithm
------------------
Inputs
  - Historical block (40% of weighted score by default):
      past marks band (mandatory), chapter exposure (0 if none selected),
      study hours, self-confidence, science self-efficacy, prerequisite checklist
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
    science_self_efficacy: int | None = None,
    prerequisite_ready_count: int | None = None,
    expected_chapters: int = 12,
) -> float:
    """Blend historical signals into [0, 1].

    Weight mix (sums to 1.0):
      marks 0.30 | chapters 0.25 | hours 0.10 | confidence 0.10 |
      self-efficacy 0.15 | prerequisites 0.10
    """
    marks = _PAST_SCORE[past_grade_marks_range]
    denom = max(1, expected_chapters)
    chapter_ratio = min(max(float(completed_chapters_count) / denom, 0.0), 1.0)
    hours = 0.5
    if study_hours_per_week is not None:
        hours = min(max(float(study_hours_per_week) / 14.0, 0.0), 1.0)
    confidence = 0.5
    if self_confidence is not None:
        confidence = min(max(int(self_confidence), 1), 5) / 5.0
    efficacy = 0.6  # default mid-high when omitted (optional field)
    if science_self_efficacy is not None:
        efficacy = min(max(int(science_self_efficacy), 1), 5) / 5.0
    prereq = 0.4  # default 2/5 when omitted
    if prerequisite_ready_count is not None:
        prereq = min(max(int(prerequisite_ready_count), 0), 5) / 5.0
    return round(
        0.30 * marks
        + 0.25 * chapter_ratio
        + 0.10 * hours
        + 0.10 * confidence
        + 0.15 * efficacy
        + 0.10 * prereq,
        4,
    )


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
