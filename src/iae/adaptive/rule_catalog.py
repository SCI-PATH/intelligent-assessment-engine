"""Stable IDs and pedagogical labels for adaptive policy rules.

Threshold copy here is descriptive; authoritative numeric thresholds live in
``policy.py`` constants and must stay aligned when tuning.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuleCatalogEntry:
    rule_id: str
    title: str
    if_summary: str
    pedagogy_tag: str


# DOK ladder ( Webb-style depth progression as target; scaffolding on failure )
RULE_DOK_R0_COLD_START = RuleCatalogEntry(
    rule_id="DOK_R0_COLD_START",
    title="Cold start baseline DOK",
    if_summary="No graded attempts yet in this session",
    pedagogy_tag="Diagnostic entry: Webb DOK as depth target (formative calibration).",
)

RULE_DOK_R1_PROGRESSION = RuleCatalogEntry(
    rule_id="DOK_R1_PROGRESSION",
    title="Step up depth of knowledge",
    if_summary=(
        "rolling average (mean graded score, last N attempts) ≥ 80% "
        "AND last graded score ≥ 85% "
        "AND response time ≤ 30s"
    ),
    pedagogy_tag="Black & Wiliam style formative band (~80–85%) + Webb DOK stretch when fluent.",
)

RULE_DOK_R2_HIGH_PROTECT = RuleCatalogEntry(
    rule_id="DOK_R2_HIGH_PROTECT",
    title="Immediate support at high DOK",
    if_summary="current DOK is 3 or 4 AND last graded score < 50%",
    pedagogy_tag="Cognitive load / scaffolding: quicker relief when abstract items fail.",
)

RULE_DOK_R3_LOW_SUSTAINED = RuleCatalogEntry(
    rule_id="DOK_R3_LOW_SUSTAINED",
    title="Sustained-struggle downshift at low DOK",
    if_summary=(
        "current DOK is 1 or 2 AND weak streak ≥ 2 (<50% scores) "
        "AND rolling average < 50% AND last graded score < 50%"
    ),
    pedagogy_tag="Avoid false negatives at basics: demand evidence across attempts before easing further.",
)

RULE_DOK_R4_HOLD = RuleCatalogEntry(
    rule_id="DOK_R4_HOLD",
    title="Hold DOK — no progression rule fired",
    if_summary="None of progression, high-DOK support, or low-DOK sustained downshift matched",
    pedagogy_tag="Zone of proximal development: dwell until evidence is decisive.",
)


RULE_TYPE_R0_COLD_START = RuleCatalogEntry(
    rule_id="TYPE_R0_COLD_START",
    title="Cold start MCQ",
    if_summary="No prior attempts — objective format first",
    pedagogy_tag="Low-friction baseline signal before expressive formats.",
)

RULE_TYPE_R1_MULTI_BLANK = RuleCatalogEntry(
    rule_id="TYPE_R1_STRONG_MULTI_BLANK",
    title="Multi-step response at higher DOK",
    if_summary="last ≥ 85% AND rolling average ≥ 80% AND planned DOK ≥ 3",
    pedagogy_tag="Webb DOK application: connected ideas under stronger evidence.",
)

RULE_TYPE_R1_SHORT_ANSWER = RuleCatalogEntry(
    rule_id="TYPE_R1_STRONG_SHORT_ANSWER",
    title="Constructed response after strong trajectory",
    if_summary="last ≥ 85% AND rolling average ≥ 80% AND planned DOK ≤ 2",
    pedagogy_tag="Elaborated knowing: explanation under secure recent performance.",
)

RULE_TYPE_R2_WEAK = RuleCatalogEntry(
    rule_id="TYPE_R2_WEAK_MCQ",
    title="Objective format after weak performance",
    if_summary="last graded score < 50%",
    pedagogy_tag="Reduce construct demand to isolate misconceptions.",
)

RULE_TYPE_R3_SLOW = RuleCatalogEntry(
    rule_id="TYPE_R3_SLOW_TRUE_FALSE",
    title="Reduced load after slow response",
    if_summary="response time > 45s",
    pedagogy_tag="Fluency / cognitive load relief while keeping retrieval.",
)

RULE_TYPE_R4_LEAST_USED = RuleCatalogEntry(
    rule_id="TYPE_R4_LEAST_USED_ROTATION",
    title="Variety — least-used concise format",
    if_summary=(
        "else — choose MCQ vs TrueFalse vs MultiBlank with lowest session counts (ties random)"
    ),
    pedagogy_tag="Practice breadth without over-weighting one format.",
)

RULE_DEFINITIONS_BY_ID: dict[str, RuleCatalogEntry] = {
    e.rule_id: e
    for e in (
        RULE_DOK_R0_COLD_START,
        RULE_DOK_R1_PROGRESSION,
        RULE_DOK_R2_HIGH_PROTECT,
        RULE_DOK_R3_LOW_SUSTAINED,
        RULE_DOK_R4_HOLD,
        RULE_TYPE_R0_COLD_START,
        RULE_TYPE_R1_MULTI_BLANK,
        RULE_TYPE_R1_SHORT_ANSWER,
        RULE_TYPE_R2_WEAK,
        RULE_TYPE_R3_SLOW,
        RULE_TYPE_R4_LEAST_USED,
    )
}
