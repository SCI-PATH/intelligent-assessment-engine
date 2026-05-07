"""Plain-language DDA policy explainer for presentations."""

from __future__ import annotations

import streamlit as st

TARGET_ACCURACY_LOWER = 0.80
TARGET_ACCURACY_UPPER = 0.85
RESPONSE_TIME_TARGET_SECONDS = 45.0


def decide_next_dok(current_dok: int, rolling_accuracy: float, response_time_seconds: float) -> tuple[int, str, str]:
    normalized_time = min(max(response_time_seconds / RESPONSE_TIME_TARGET_SECONDS, 0.0), 2.0)
    theta = (rolling_accuracy - 0.5) * 2.0
    item_b = (current_dok - 2.5) / 1.5
    gap = theta - item_b

    if normalized_time >= 0.85 and rolling_accuracy < TARGET_ACCURACY_UPPER:
        next_dok = max(1, current_dok - 1)
        reason = (
            "The student is taking longer than expected and accuracy is not strong, "
            "so the engine reduces difficulty to avoid overload."
        )
        rule = "slow-response safety rule"
    elif rolling_accuracy < TARGET_ACCURACY_LOWER:
        next_dok = max(1, current_dok - 1)
        reason = "Accuracy is below target, so the engine lowers DOK to rebuild confidence."
        rule = "below-target accuracy rule"
    elif rolling_accuracy > TARGET_ACCURACY_UPPER and normalized_time <= 0.45 and gap > 0.20:
        next_dok = min(4, current_dok + 1)
        reason = "Accuracy is high and responses are fast, so the engine raises difficulty."
        rule = "high-performance progression rule"
    else:
        next_dok = current_dok
        reason = "Performance is within the target zone, so the engine keeps difficulty stable."
        rule = "stability rule"

    return next_dok, rule, reason


def main() -> None:
    st.set_page_config(page_title="DDA Decision Explainer", layout="centered")
    st.title("Adaptive Difficulty Decision Explainer")

    current_dok = st.selectbox("Current DOK", [1, 2, 3, 4], index=1)
    rolling_accuracy = st.slider("Rolling accuracy", 0.0, 1.0, 0.80, 0.01)
    response_time_seconds = st.slider("Response time (seconds)", 0, 90, 22, 1)

    next_dok, rule, reason = decide_next_dok(
        current_dok=current_dok,
        rolling_accuracy=rolling_accuracy,
        response_time_seconds=float(response_time_seconds),
    )

    st.divider()
    st.subheader("Decision")
    st.markdown(f"- **Triggered rule:** {rule}")
    st.markdown(f"- **Current DOK:** {current_dok}")
    st.markdown(f"- **Next DOK:** {next_dok}")
    st.markdown(f"- **Why:** {reason}")

    with st.expander("Show technical values"):
        normalized_time = min(max(float(response_time_seconds) / RESPONSE_TIME_TARGET_SECONDS, 0.0), 2.0)
        theta = (rolling_accuracy - 0.5) * 2.0
        item_b = (current_dok - 2.5) / 1.5
        st.markdown(f"- response time (seconds): `{response_time_seconds}`")
        st.markdown(
            f"- normalized response time used by policy: `{normalized_time:.2f}` "
            f"(seconds / {int(RESPONSE_TIME_TARGET_SECONDS)})"
        )
        st.markdown(f"- theta (estimated ability): `{theta:.2f}`")
        st.markdown(f"- b (current item difficulty proxy): `{item_b:.2f}`")
        st.markdown(f"- theta - b gap: `{(theta - item_b):.2f}`")


if __name__ == "__main__":
    main()
