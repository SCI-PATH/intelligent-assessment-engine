"""Unit tests for Aptitude scoring and category cutoffs (no DB)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from iae.application.amplitude_scoring import (
    categorize,
    history_composite_score,
    weighted_amplitude_score,
)
from iae.application.amplitude_service import resolve_chapter_selection, AmplitudeSurveyInvalid
from iae.domain.models import AmplitudeCategory, PastGradeMarksRange


def test_categorize_boundaries() -> None:
    assert categorize(0.0) == AmplitudeCategory.BASIC
    assert categorize(0.4499) == AmplitudeCategory.BASIC
    assert categorize(0.45) == AmplitudeCategory.INTERMEDIATE
    assert categorize(0.75) == AmplitudeCategory.INTERMEDIATE
    assert categorize(0.7501) == AmplitudeCategory.ADVANCED
    assert categorize(1.0) == AmplitudeCategory.ADVANCED


def test_zero_chapters_history() -> None:
    score = history_composite_score(
        past_grade_marks_range=PastGradeMarksRange.BELOW_50,
        completed_chapters_count=0,
        study_hours_per_week=0.0,
        self_confidence=1,
        science_self_efficacy=1,
        prerequisite_ready_count=0,
        expected_chapters=11,
    )
    assert 0.0 <= score <= 1.0
    # Low marks + no chapters + low efficacy should keep history modest.
    assert score < 0.45


def test_strong_history() -> None:
    score = history_composite_score(
        past_grade_marks_range=PastGradeMarksRange.ABOVE_75,
        completed_chapters_count=11,
        study_hours_per_week=14.0,
        self_confidence=5,
        science_self_efficacy=5,
        prerequisite_ready_count=5,
        expected_chapters=11,
    )
    assert score > 0.75


def test_weighted_blend() -> None:
    # Perfect quiz + mid history → still ADVANCED-ish depending on history
    w = weighted_amplitude_score(quiz_score=1.0, history_score=0.5)
    assert w == 0.8
    assert categorize(w) == AmplitudeCategory.ADVANCED

    w_basic = weighted_amplitude_score(quiz_score=0.2, history_score=0.2)
    assert categorize(w_basic) == AmplitudeCategory.BASIC

    w_mid = weighted_amplitude_score(quiz_score=0.5, history_score=0.5)
    assert categorize(w_mid) == AmplitudeCategory.INTERMEDIATE


def test_empty_chapter_ids() -> None:
    ids, count = resolve_chapter_selection(
        grade=6,
        completed_chapter_ids=[],
        completed_chapters_count=None,
    )
    assert ids == []
    assert count == 0


def test_invalid_chapter_grade() -> None:
    try:
        resolve_chapter_selection(
            grade=6,
            completed_chapter_ids=["G7_C1"],
            completed_chapters_count=None,
        )
    except AmplitudeSurveyInvalid:
        return
    raise AssertionError("expected AmplitudeSurveyInvalid")


def test_legacy_count_only() -> None:
    ids, count = resolve_chapter_selection(
        grade=7,
        completed_chapter_ids=None,
        completed_chapters_count=3,
    )
    assert ids == []
    assert count == 3


def main() -> int:
    test_categorize_boundaries()
    test_zero_chapters_history()
    test_strong_history()
    test_weighted_blend()
    test_empty_chapter_ids()
    test_invalid_chapter_grade()
    test_legacy_count_only()
    print("APTITUDE_SCORING_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
