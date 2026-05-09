"""Streamlit demo client for the Intelligent Assessment Engine."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8001")
TIMEOUT_SECONDS = 60
TARGET_ACCURACY_LOWER = 0.80
TARGET_ACCURACY_UPPER = 0.85
RESPONSE_TIME_TARGET_SECONDS = 45.0


def _as_clean_text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _simple_reason(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    for prefix in ("Why this DOK?", "Why DOK 1?", "Why DOK 2?", "Why DOK 3?", "Why DOK 4?", "Action:"):
        cleaned = cleaned.replace(prefix, "").strip()
    return cleaned


def _condition_symbol(met: Any) -> str:
    if met is True:
        return "✓"
    if met is False:
        return "✗"
    return "—"


def _render_rule_trace_block(
    *,
    heading: str,
    trace: dict[str, Any] | None,
    legacy_line: str = "",
) -> None:
    st.markdown(f"**{heading}**")
    if not trace:
        if legacy_line:
            st.caption(_simple_reason(legacy_line))
        else:
            st.caption("No structured trace in payload (legacy session).")
        return
    rule_id = trace.get("rule_id", "")
    title = trace.get("title", "")
    st.markdown(f"{title} (`{rule_id}`)")
    ped = (trace.get("pedagogy_tag") or "").strip()
    if ped:
        st.caption(ped)
    st.markdown("**IF (evaluated):**")
    for cond in trace.get("conditions") or []:
        label = cond.get("label", "")
        obs = cond.get("observed", "")
        sym = _condition_symbol(cond.get("met"))
        st.markdown(f"- {sym} {label}  —  observed: `{obs}`")
    outcome = (trace.get("outcome") or "").strip()
    if outcome:
        st.markdown(f"**{outcome}**")


def _api_get(path: str) -> dict[str, Any]:
    response = requests.get(f"{API_BASE_URL}{path}", timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _api_post(path: str, payload: dict | None = None) -> dict[str, Any]:
    response = requests.post(f"{API_BASE_URL}{path}", json=payload or {}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _ensure_state() -> None:
    defaults = {
        "session_id": None,
        "scope_chapter": None,
        "max_questions": 5,
        "current": None,
        "grade": None,
        "is_complete": False,
        "question_started_at": None,
        "results": None,
        "show_answers": True,
        "last_response_time_seconds": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _reset_session() -> None:
    for key in ("session_id", "scope_chapter", "current", "grade", "is_complete", "question_started_at", "results"):
        st.session_state[key] = None
    st.session_state["is_complete"] = False
    for key in list(st.session_state.keys()):
        if key.startswith("blank_"):
            del st.session_state[key]


def _fetch_next_question() -> None:
    payload = _api_post(f"/assessment/sessions/{st.session_state.session_id}/next")
    st.session_state.current = payload
    st.session_state.grade = None
    st.session_state.question_started_at = time.time()


def _submit_answer(student_answer: str) -> None:
    elapsed = time.time() - (st.session_state.question_started_at or time.time())
    payload = {
        "question_id": st.session_state.current["question"]["_id"],
        "student_answer": student_answer,
        "time_taken_seconds": float(elapsed),
    }
    response = _api_post(f"/assessment/sessions/{st.session_state.session_id}/answer", payload)
    st.session_state.grade = response
    st.session_state.is_complete = response.get("is_complete", False)
    st.session_state.last_response_time_seconds = float(elapsed)


def _load_results() -> None:
    st.session_state.results = _api_get(f"/assessment/sessions/{st.session_state.session_id}/results")


def _answer_key_text(question: dict[str, Any]) -> str:
    qtype = question.get("question_type")
    payload = question.get("payload", {})
    if qtype == "MCQ":
        key = payload.get("correct_answer")
        label = payload.get("options", {}).get(key, "")
        return f"MCQ correct answer: {key}) {label}"
    if qtype == "TrueFalse":
        return f"True/False answer: {payload.get('correct_answer', 'N/A')}"
    if qtype == "MultiBlank":
        answers = payload.get("answers", [])
        return "Multi-blank answers: " + ", ".join(str(a) for a in answers)
    ideal = payload.get("ideal_answer", "N/A")
    keywords = ", ".join(payload.get("keywords", []))
    return f"Ideal answer: {ideal}\nKeywords: {keywords}"


_BLANK_PATTERN = re.compile(r"\[_+\]|_{3,}|\[\s*blank\s*\d+\s*\]|\[\s*\]", re.IGNORECASE)


def _count_blanks(paragraph: str) -> int:
    return len(_BLANK_PATTERN.findall(paragraph))


def _render_paragraph_with_visible_blanks(paragraph: str) -> str:
    # Render as true blank slots, not numbered labels.
    return _BLANK_PATTERN.sub("[_____]", paragraph)


def render_xray_panel(payload: dict[str, Any]) -> None:
    """Compact diagnostics panel with plain-English control trace."""
    telemetry = payload["telemetry"]
    state = telemetry["state"]
    action = telemetry["action"]
    question = payload["question"]

    prev_dok = int(state.get("current_difficulty", 2))
    target_dok = int(action.get("next_difficulty_level", prev_dok))
    served_dok = int(question.get("dok_level", target_dok))
    served_type = question.get("question_type", "N/A")
    target_type = action.get("next_question_type", "N/A")
    rolling = float(telemetry.get("rolling_accuracy", 0.0))
    last_acc = float(state.get("accuracy_score", 0.0))
    response_seconds = float(action.get("previous_response_time_seconds", 0.0) or 0.0)
    if response_seconds <= 0.0:
        response_seconds = float(state.get("response_time_seconds", 0.0) or 0.0)
    if response_seconds <= 0.0 and st.session_state.get("last_response_time_seconds") is not None:
        response_seconds = float(st.session_state["last_response_time_seconds"])

    with st.container(border=True):
        st.markdown("**Adaptive Decision Trace**")
        time_text = f"{response_seconds:.1f}s" if response_seconds > 0.0 else "N/A (first item)"
        st.caption(
            "[ Inputs: "
            f"Rolling avg (mean score): {rolling:.0%} | "
            f"Last score: {last_acc:.0%} | "
            f"Time: {time_text} ]"
        )
        st.markdown(f"**Transition:** Previous DOK {prev_dok} -> Target DOK {target_dok}")

        dok_trace = action.get("dok_trace")
        type_trace = action.get("type_trace")
        dok_legacy = ""
        if not dok_trace:
            dok_r = _as_clean_text(action.get("dok_reason"), "")
            if not dok_r:
                if target_dok > prev_dok:
                    dok_legacy = (
                        "Difficulty increased because recent scores support stepping up "
                        "(legacy fallback text)."
                    )
                elif target_dok < prev_dok:
                    dok_legacy = "Difficulty reduced for support (legacy fallback text)."
                else:
                    dok_legacy = "Difficulty unchanged (legacy fallback text)."
            else:
                dok_legacy = dok_r
        qt_legacy = ""
        if not type_trace:
            qt_r = _as_clean_text(action.get("question_type_reason"), "")
            qt_legacy = qt_r or "Question type fallback (legacy)."

        _render_rule_trace_block(heading="DOK rule", trace=dok_trace if isinstance(dok_trace, dict) else None, legacy_line=dok_legacy)
        _render_rule_trace_block(
            heading="Question type rule",
            trace=type_trace if isinstance(type_trace, dict) else None,
            legacy_line=qt_legacy,
        )

        summaries = [_as_clean_text(action.get("dok_summary"), ""), _as_clean_text(action.get("type_summary"), "")]
        short = " | ".join(s for s in summaries if s)
        if short:
            st.caption(f"Summaries: {short}")

        if served_type != target_type:
            st.caption(f"Served type fallback: requested {target_type}, served {served_type}.")
        if served_dok != target_dok:
            st.warning(
                f"Conflict note: policy targeted DOK {target_dok} but question bank served DOK {served_dok} "
                "(availability fallback, not a policy bug)."
            )
        if action.get("rapid_guessing_detected"):
            st.warning("Rapid guess: DOK increase held.")
        if action.get("format_simplification_triggered"):
            st.info("Format simplification at same DOK.")


def render_start_screen() -> None:
    st.subheader("Start a diagnostic session")
    st.caption("Pick a chapter to begin. The engine will choose every question for you.")

    try:
        chapters_payload = _api_get("/assessment/chapters")
    except requests.RequestException as exc:
        st.error(f"Backend unreachable: {exc}")
        return

    chapter = st.selectbox("Chapter", chapters_payload["chapters"])
    st.checkbox("Show answer key (testing mode)", key="show_answers")
    st.session_state.max_questions = chapters_payload["max_questions"]
    st.write(f"Session length: **{st.session_state.max_questions} questions**")

    if st.button("Start assessment", type="primary"):
        with st.spinner("Initializing session..."):
            try:
                session = _api_post("/assessment/sessions", {"chapter_name": chapter})
                st.session_state.session_id = session["session_id"]
                st.session_state.scope_chapter = session["scope_chapter"]
                _fetch_next_question()
            except requests.RequestException as exc:
                st.error(f"Could not start session: {exc}")
                return
        st.rerun()


def render_question_panel() -> None:
    payload = st.session_state.current
    question = payload["question"]
    qtype = question["question_type"]
    body = question["payload"]

    asked = payload["telemetry"]["questions_asked"] + 1
    st.progress(asked / st.session_state.max_questions, text=f"Question {asked} of {st.session_state.max_questions}")
    st.caption(f"Chapter: {question['chapter_name']}  |  DOK {question['dok_level']}  |  Type: {qtype}")

    # Two-column layout: quiz left, compact trace right. Render the trace column first so an early
    # return in the quiz column (after Submit) never skips the side panel on first paint.
    left, right = st.columns([11, 5], gap="medium")
    with right:
        render_xray_panel(payload)

    with left:
        if st.session_state.get("show_answers", True):
            with st.expander("Answer key (testing mode)", expanded=False):
                st.write(_answer_key_text(question))

        student_answer = _render_question_inputs(qtype, body)

        if st.session_state.grade is None:
            if st.button("Submit answer", type="primary", disabled=student_answer is None):
                with st.spinner("Grading..."):
                    try:
                        _submit_answer(student_answer)
                    except requests.RequestException as exc:
                        st.error(f"Could not submit answer: {exc}")
                        return
                st.rerun()
            return

        grade = st.session_state.grade["grade"]
        score_pct = int(round(grade["accuracy_score"] * 100))
        if qtype == "ShortAnswer" and grade.get("reasoning"):
            st.info(f"Score: {score_pct}%  |  {grade['feedback']} {grade['reasoning']}")
        else:
            if grade["is_correct"]:
                st.success(f"Score: {score_pct}%  |  {grade['feedback']}")
            else:
                st.warning(f"Score: {score_pct}%  |  {grade['feedback']}")

        if st.session_state.is_complete:
            if st.button("View results", type="primary"):
                _load_results()
                st.rerun()
        else:
            if st.button("Next question", type="primary"):
                try:
                    _fetch_next_question()
                except requests.RequestException as exc:
                    st.error(f"Could not fetch next question: {exc}")
                    return
                st.rerun()


def _render_question_inputs(qtype: str, body: dict) -> str | None:
    if qtype == "MCQ":
        st.markdown(f"### {body['question']}")
        choices = [f"{k}) {v}" for k, v in body["options"].items()]
        chosen = st.radio("Select an option", choices, index=None)
        return chosen[0] if chosen else None

    if qtype == "TrueFalse":
        st.markdown(f"### {body['question']}")
        chosen = st.radio("True or False?", ["True", "False"], index=None)
        return chosen

    if qtype == "MultiBlank":
        paragraph = body.get("paragraph", "")
        answers = body.get("answers", [])
        st.markdown(f"### {_render_paragraph_with_visible_blanks(paragraph)}")

        blank_count = _count_blanks(paragraph)
        if blank_count == 0 and answers:
            blank_count = len(answers)
            st.info("Fill the missing parts in order:\n\n" + "  ".join([f"**[ Blank {i + 1} ]**" for i in range(blank_count)]))

        values: list[str] = []
        for i in range(blank_count):
            value = st.text_input(f"Blank {i + 1}", key=f"blank_{st.session_state.session_id}_{paragraph[:20]}_{i}")
            values.append(value.strip())
        if not any(values):
            return None
        return json.dumps(values)

    st.markdown(f"### {body['question']}")
    text = st.text_area("Your answer", height=120)
    return text or None


def render_results_screen() -> None:
    if st.session_state.results is None:
        _load_results()
    results = st.session_state.results
    st.subheader("Diagnostic results")
    st.metric(
        f"Final score for {results['scope_chapter']}",
        f"{results['correct_count']} / {results['questions_asked']}",
        delta=f"{results['raw_accuracy'] * 100:.0f}% raw accuracy",
        delta_color="off",
    )

    st.markdown("### Per-question review")
    for idx, attempt in enumerate(results["history"], start=1):
        score_pct = attempt["accuracy_score"] * 100
        badge = "Correct" if attempt["is_correct"] else "Incorrect"
        st.markdown(f"**Q{idx}** ({attempt['question_type']} | DOK {attempt['dok_level']}) - {badge} ({score_pct:.0f}%)")
        st.markdown(f"_Your answer:_ {attempt['student_answer'] or '*(blank)*'}")
        if attempt.get("question_type") == "ShortAnswer" and attempt.get("reasoning"):
            st.caption(f"Score rationale: {attempt.get('feedback', '')} {attempt.get('reasoning', '')}".strip())
        elif attempt.get("feedback"):
            st.caption(attempt["feedback"])
        trace_rolling = attempt.get("decision_rolling_accuracy")
        trace_last = attempt.get("decision_last_accuracy")
        trace_time = attempt.get("time_taken_seconds")
        trace_prev_dok = attempt.get("decision_prev_dok")
        trace_target_dok = attempt.get("decision_target_dok")
        dok_tr = attempt.get("decision_dok_trace")
        typ_tr = attempt.get("decision_type_trace")

        trace_reason = (attempt.get("decision_dok_reason") or "").strip()
        trace_format = (attempt.get("decision_question_type_reason") or "").strip()
        show_block = (
            trace_rolling is not None
            or trace_last is not None
            or trace_time is not None
            or trace_reason
            or trace_format
            or dok_tr
            or typ_tr
        )
        if show_block:
            st.caption("[ Decision Trace ]")
            if trace_rolling is not None and trace_last is not None and trace_time is not None:
                st.caption(
                    f"Inputs: Rolling avg (mean score): {float(trace_rolling):.0%} | "
                    f"Last score: {float(trace_last):.0%} | "
                    f"Time: {float(trace_time):.1f}s"
                )
            if trace_prev_dok is not None and trace_target_dok is not None:
                st.caption(f"Transition: Previous DOK {trace_prev_dok} -> Target DOK {trace_target_dok}")
            col_a, col_b = st.columns(2)
            with col_a:
                _render_rule_trace_block(
                    heading="DOK",
                    trace=dok_tr if isinstance(dok_tr, dict) else None,
                    legacy_line=trace_reason,
                )
            with col_b:
                _render_rule_trace_block(
                    heading="Type",
                    trace=typ_tr if isinstance(typ_tr, dict) else None,
                    legacy_line=trace_format,
                )
        st.divider()

    if st.button("New session", type="primary"):
        _reset_session()
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="Intelligent Assessment Engine", layout="wide")
    _ensure_state()
    st.title("Intelligent Assessment Engine")
    st.caption("Diagnostic real-time question selection.")

    if st.session_state.session_id is None:
        render_start_screen()
        return

    if st.session_state.results is not None:
        render_results_screen()
        return

    render_question_panel()


if __name__ == "__main__":
    main()
