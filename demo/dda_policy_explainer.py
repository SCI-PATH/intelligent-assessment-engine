"""Interactive preview of the adaptive difficulty policy (same rules as the live assessment)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iae.adaptive import rule_catalog as rc  # noqa: E402

_LAST_WEAK_ACC = 0.50
_LAST_STRONG_ACC = 0.85
_ROLL_UP = 0.80
_SLOW_SECONDS = 45.0
_FAST_UP_SECONDS = 30.0


def evaluate(
    *,
    current_dok: int,
    rolling_average: float,
    last_accuracy: float,
    weak_streak: int,
    response_time_seconds: float,
) -> tuple[int, str, str, str, str, str, str, str]:
    """next_dok, next_type, dok_id, typ_id, dok_heading, dok_one_liner, type_heading, type_one_liner."""

    weak_last = last_accuracy < _LAST_WEAK_ACC
    increase_ok = (
        rolling_average >= _ROLL_UP
        and last_accuracy >= _LAST_STRONG_ACC
        and response_time_seconds <= _FAST_UP_SECONDS
    )
    decrease_high_dok = current_dok >= 3 and weak_last
    decrease_low_dok = (
        current_dok <= 2
        and weak_streak >= 2
        and rolling_average < _LAST_WEAK_ACC
        and weak_last
    )

    if increase_ok:
        next_dok = min(4, current_dok + 1)
        dok_fired_id = rc.RULE_DOK_R1_PROGRESSION.rule_id
        dok_head = "DOK · Step 1 — step up"
        dok_line = (
            f"Rolling {rolling_average:.0%}, last {last_accuracy:.0%}, time {response_time_seconds:.1f}s met the bar → **DOK {current_dok}→{next_dok}**."
        )
    elif decrease_high_dok:
        next_dok = max(1, current_dok - 1)
        dok_fired_id = rc.RULE_DOK_R2_HIGH_PROTECT.rule_id
        dok_head = "DOK · Step 2 — help on hard depth"
        dok_line = f"On DOK {current_dok} with last score {last_accuracy:.0%} → **DOK {current_dok}→{next_dok}**."
    elif decrease_low_dok:
        next_dok = max(1, current_dok - 1)
        dok_fired_id = rc.RULE_DOK_R3_LOW_SUSTAINED.rule_id
        dok_head = "DOK · Step 3 — ease after repeated struggle"
        dok_line = f"Weak streak {weak_streak}, rolling {rolling_average:.0%}, last {last_accuracy:.0%} → **DOK {current_dok}→{next_dok}**."
    else:
        next_dok = current_dok
        dok_fired_id = rc.RULE_DOK_R4_HOLD.rule_id
        dok_head = "DOK · Step 4 — no change"
        dok_line = f"Nothing in steps 1–3 fully matched → stays **{next_dok}**."

    if last_accuracy >= _LAST_STRONG_ACC and rolling_average >= _ROLL_UP:
        if next_dok >= 3:
            next_type = "MultiBlank"
            type_fired_id = rc.RULE_TYPE_R1_MULTI_BLANK.rule_id
            type_head = "Type · Step 1 strong + higher next DOK"
            type_line = f"Next DOK planned as {next_dok} → **MultiBlank**."
        else:
            next_type = "ShortAnswer"
            type_fired_id = rc.RULE_TYPE_R1_SHORT_ANSWER.rule_id
            type_head = "Type · Step 1 strong + lower next DOK"
            type_line = f"Next DOK planned as {next_dok} → **Short answer**."
    elif last_accuracy < _LAST_WEAK_ACC:
        next_type = "MCQ"
        type_fired_id = rc.RULE_TYPE_R2_WEAK.rule_id
        type_head = "Type · Step 2 weak last answer"
        type_line = f"Last {last_accuracy:.0%} → **MCQ**."
    elif response_time_seconds > _SLOW_SECONDS:
        next_type = "TrueFalse"
        type_fired_id = rc.RULE_TYPE_R3_SLOW.rule_id
        type_head = "Type · Step 3 slow response"
        type_line = f"{response_time_seconds:.1f}s → **True/False**."
    else:
        next_type = "Rotate (MCQ / T-F / Multi-blank)"
        type_fired_id = rc.RULE_TYPE_R4_LEAST_USED.rule_id
        type_head = "Type · Step 4 middle signals"
        type_line = "Least-used of MCQ · True/false · Multi-blank in this session."

    return next_dok, next_type, dok_fired_id, type_fired_id, dok_head, dok_line, type_head, type_line


_RULES_BOTTOM = """### Rules

Read **top to bottom**. Use the **first** row that fits.

#### Question depth (DOK)

| Rule ID | If… | Then… |
|:---|:---|:---|
| `DOK_R0_COLD_START` | No graded attempt in the session yet | Next depth = **starting** value from settings |
| `DOK_R1_PROGRESSION` | Rolling average ≥ **80%** AND last score ≥ **85%** AND time ≤ **30** s | Depth **goes up by one** (max **4**) |
| `DOK_R2_HIGH_PROTECT` | Depth is **3 or 4** AND last score **under 50%** | Depth **goes down by one** |
| `DOK_R3_LOW_SUSTAINED` | Depth is **1 or 2** AND **two** answers in a row **under 50%** AND rolling average **under 50%** AND last **under 50%** | Depth **goes down by one** |
| `DOK_R4_HOLD` | None of the rows above matched | **Keep** the same depth |

#### Question format

| Rule ID | If… | Then… |
|:---|:---|:---|
| `TYPE_R0_COLD_START` | First question — no prior attempts | **Multiple choice** |
| `TYPE_R1_STRONG_MULTI_BLANK` | Last ≥ **85%** AND rolling average ≥ **80%** AND **planned** next depth is **3 or 4** | **Multi-blank** |
| `TYPE_R1_STRONG_SHORT_ANSWER` | Last ≥ **85%** AND rolling average ≥ **80%** AND **planned** next depth is **1 or 2** | **Short answer** |
| `TYPE_R2_WEAK_MCQ` | Last score **under 50%** | **Multiple choice** |
| `TYPE_R3_SLOW_TRUE_FALSE` | Time **over 45** seconds | **True / false** |
| `TYPE_R4_LEAST_USED_ROTATION` | None of the rows above matched | **Multiple choice / true-false / multi-blank** — whichever was used **least** in the session |
"""


def main() -> None:
    st.set_page_config(page_title="Difficulty policy", layout="wide")
    st.title("What changes next")

    with st.sidebar:
        st.header("Try numbers")
        current_dok = st.select_slider("Current DOK", options=[1, 2, 3, 4], value=2)
        rolling_average = st.slider("Rolling avg (recent scores)", 0.0, 1.0, 0.72, 0.01)
        last_accuracy = st.slider("Last answer score", 0.0, 1.0, 0.80, 0.01)
        weak_streak = st.slider(
            "Runs in a row under 50% (weak streak)",
            0,
            5,
            0,
            help=(
                "Count answers with graded score below 50%, from the newest backward until one is 50%+ . "
                "Only used for DOK step 3. Not the live quiz “correct streak” (consecutive passes / is_correct)—that counts passes, "
                "not how low numeric scores ran together."
            ),
        )
        response_time_seconds = st.slider("Last response time (s)", 0, 90, 22)

    (
        next_dok,
        next_type,
        dok_id,
        typ_id,
        dok_head,
        dok_line,
        type_head,
        type_line,
    ) = evaluate(
        current_dok=current_dok,
        rolling_average=float(rolling_average),
        last_accuracy=float(last_accuracy),
        weak_streak=int(weak_streak),
        response_time_seconds=float(response_time_seconds),
    )

    st.caption("Use the sidebar to try values. Below the line: the full rule list.")

    lc, rc = st.columns(2, gap="large")
    with lc:
        with st.container(border=True):
            st.markdown(f"###### {dok_head}")
            st.metric("Depth of knowledge", f"{current_dok}  →  {next_dok}")
            st.write(dok_line)
            st.caption(f"Rule **`{dok_id}`**")
    with rc:
        with st.container(border=True):
            st.markdown(f"###### {type_head}")
            st.metric("Question format", next_type)
            st.write(type_line)
            st.caption(f"Rule **`{typ_id}`**")

    st.markdown("---")
    st.markdown(_RULES_BOTTOM)


if __name__ == "__main__":
    main()
