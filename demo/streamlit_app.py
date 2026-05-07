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


_BLANK_PATTERN = re.compile(r"\[_+\]|_{3,}|\[\s*blank\s*\d+\s*\]", re.IGNORECASE)


def _count_blanks(paragraph: str) -> int:
    return len(_BLANK_PATTERN.findall(paragraph))


def _render_paragraph_with_visible_blanks(paragraph: str) -> str:
    idx = {"i": 0}

    def replace(_m: re.Match[str]) -> str:
        idx["i"] += 1
        return f"*[_Blank {idx['i']}_]*"

    return _BLANK_PATTERN.sub(replace, paragraph)


def _decision_for_current_question(payload: dict[str, Any], question: dict[str, Any]) -> tuple[str, str]:
    telemetry = payload["telemetry"]
    state = telemetry["state"]
    rolling = float(telemetry.get("rolling_accuracy", 0.0))
    normalized_time = float(state.get("time_taken", 0.0))
    current_dok = int(question.get("dok_level", state.get("current_difficulty", 2)))

    if int(telemetry.get("questions_asked", 0)) == 0:
        return (
            "cold-start rule",
            f"Current DOK is {current_dok} because the session always starts from the configured baseline difficulty.",
        )

    theta = (rolling - 0.5) * 2.0
    item_b = (current_dok - 2.5) / 1.5
    gap = theta - item_b

    if normalized_time >= 0.85 and rolling < TARGET_ACCURACY_UPPER:
        rule = "slow-response safety rule"
        why = (
            f"Current DOK is {current_dok} because the student took longer than expected "
            "and accuracy was not strong, so the engine reduced difficulty to avoid overload."
        )
    elif rolling < TARGET_ACCURACY_LOWER:
        rule = "below-target accuracy rule"
        why = (
            f"Current DOK is {current_dok} because rolling accuracy was below target, "
            "so the engine lowered difficulty to rebuild confidence."
        )
    elif rolling > TARGET_ACCURACY_UPPER and normalized_time <= 0.45 and gap > 0.20:
        rule = "high-performance progression rule"
        why = (
            f"Current DOK is {current_dok} because the student was both accurate and fast, "
            "so the engine increased challenge."
        )
    else:
        rule = "stability rule"
        why = (
            f"Current DOK is {current_dok} because performance was in the target range, "
            "so the engine kept the difficulty stable."
        )

    return rule, why


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

    rule, why = _decision_for_current_question(payload, question)
    with st.container(border=True):
        st.markdown("**Decision**")
        st.markdown(f"Triggered rule: `{rule}`")
        st.markdown(why)

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
        if attempt.get("feedback"):
            st.caption(attempt["feedback"])
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
