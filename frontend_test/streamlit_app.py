"""Streamlit harness for Component 2 /api/v1/assessment-engine flows."""

from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8001")
PREFIX = "/api/v1/assessment-engine"
TIMEOUT = 90

MOCK_USERS = {
    "mock-student-unassigned": {
        "label": "Student (unassigned)",
        "role": "student",
        "grade": 7,
        "class_code": None,
    },
    "mock-student-class-a": {
        "label": "Student (CLASS-A)",
        "role": "student",
        "grade": 7,
        "class_code": "CLASS-A",
    },
    "mock-teacher-1": {
        "label": "Teacher One (CLASS-A)",
        "role": "teacher",
        "grade": None,
        "class_code": "CLASS-A",
    },
}


def _url(path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{API_BASE_URL}{PREFIX}{path}"


def _get(path: str, **params: Any) -> Any:
    response = requests.get(_url(path), params=params or None, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def _post(path: str, payload: dict | None = None) -> Any:
    response = requests.post(_url(path), json=payload or {}, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def _api_error(exc: Exception) -> None:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        st.error(f"HTTP {exc.response.status_code}: {exc.response.text}")
    elif isinstance(exc, requests.ConnectionError):
        st.error(f"Cannot reach API at `{API_BASE_URL}`. Start uvicorn on port 8001.")
    else:
        st.error(str(exc))


def page_login() -> None:
    st.title("IAE Assessment Engine — frontend_test")
    st.caption(
        f"API: `{API_BASE_URL}{PREFIX}` — seed: `python -m scripts.db.seed_mock_users`"
    )
    choice = st.selectbox(
        "Mock user",
        options=list(MOCK_USERS.keys()),
        format_func=lambda uid: f"{MOCK_USERS[uid]['label']} (`{uid}`)",
    )
    if st.button("Sign in", type="primary"):
        st.session_state.user_id = choice
        st.session_state.user_meta = MOCK_USERS[choice]
        st.rerun()


def page_amplitude(user_id: str, grade: int) -> None:
    st.header("Amplitude Diagnostic Test")
    with st.form("amplitude_survey"):
        g = st.selectbox("Grade (local override)", [6, 7, 8, 9], index=[6, 7, 8, 9].index(grade))
        marks = st.selectbox("Past marks (required)", ["BELOW_50", "50_75", "ABOVE_75"], index=1)
        hours = st.number_input("Study hours / week", min_value=0.0, max_value=40.0, value=5.0)
        confidence = st.slider("Self-confidence", 1, 5, 3)
        efficacy = st.slider("Science self-efficacy", 1, 5, 3)
        prereq = st.slider("Prerequisite ready count", 0, 5, 2)
        zero_chapters = st.checkbox("No chapters completed yet", value=True)
        submitted = st.form_submit_button("Save survey")
    if submitted:
        try:
            body = {
                "user_id": user_id,
                "grade": g,
                "completed_chapter_ids": [],
                "past_grade_marks_range": marks,
                "study_hours_per_week": float(hours),
                "self_confidence": int(confidence),
                "science_self_efficacy": int(efficacy),
                "prerequisite_ready_count": int(prereq),
            }
            if not zero_chapters:
                body["completed_chapter_ids"] = [f"G{g}_C1"]
            profile = _post("/amplitude/survey", body)
            st.success("Survey saved")
            st.json(profile)
            st.session_state.amp_grade = g
            st.session_state.amp_marks = marks
            st.session_state.amp_hours = float(hours)
            st.session_state.amp_conf = int(confidence)
            st.session_state.amp_efficacy = int(efficacy)
            st.session_state.amp_prereq = int(prereq)
            st.session_state.amp_chapter_ids = body["completed_chapter_ids"]
        except Exception as exc:
            _api_error(exc)

    if st.button("Load fixed 10-item quiz"):
        try:
            quiz = _get("/amplitude/quiz", grade=st.session_state.get("amp_grade", grade))
            st.session_state.amp_quiz = quiz
            st.session_state.amp_answers = {}
            st.success(f"Loaded count={quiz.get('count')}")
        except Exception as exc:
            _api_error(exc)

    quiz = st.session_state.get("amp_quiz")
    if quiz:
        answers: dict[str, str] = st.session_state.get("amp_answers", {})
        for item in quiz.get("questions", []):
            qid = item["id"]
            prompt = item.get("prompt") or {}
            st.markdown(f"**{prompt.get('question') or prompt.get('paragraph') or qid}**")
            qtype = item.get("question_type")
            if qtype == "MCQ":
                options = prompt.get("options") or {}
                choice = st.radio(
                    qid,
                    options=list(options.keys()),
                    format_func=lambda k, o=options: f"{k}: {o.get(k, '')}",
                    key=f"amp_{qid}",
                )
                answers[qid] = choice
            elif qtype == "TrueFalse":
                answers[qid] = st.radio(qid, ["True", "False"], key=f"amp_{qid}")
            else:
                answers[qid] = st.text_input(qid, key=f"amp_{qid}")
        st.session_state.amp_answers = answers
        if st.button("Evaluate Amplitude", type="primary"):
            try:
                result = _post(
                    "/amplitude/evaluate",
                    {
                        "user_id": user_id,
                        "grade": st.session_state.get("amp_grade", grade),
                        "completed_chapter_ids": st.session_state.get("amp_chapter_ids", []),
                        "past_grade_marks_range": st.session_state.get("amp_marks", "50_75"),
                        "study_hours_per_week": st.session_state.get("amp_hours"),
                        "self_confidence": st.session_state.get("amp_conf"),
                        "science_self_efficacy": st.session_state.get("amp_efficacy", 3),
                        "prerequisite_ready_count": st.session_state.get("amp_prereq", 2),
                        "answers": answers,
                    },
                )
                st.success(f"Category: **{result.get('category')}**")
                st.json(result)
            except Exception as exc:
                _api_error(exc)

    if st.button("Fetch initial-category (C1 read)"):
        try:
            st.json(_get(f"/students/{user_id}/initial-category"))
        except Exception as exc:
            _api_error(exc)


def _render_question_prompt(q: dict) -> None:
    payload = q.get("payload") or {}
    # Never show keys / diagnostics to the student UI.
    text = payload.get("question") or payload.get("paragraph") or q.get("id")
    st.write(text)
    if payload.get("options"):
        for letter, opt in payload["options"].items():
            st.caption(f"{letter}: {opt}")


def page_customizable(user_id: str, grade: int) -> None:
    st.header("Customizable Quiz (Elo DDA)")
    chapter = st.text_input(
        "Chapter ID(s)",
        value="G6_C7",
        help="Canonical id from data/chapter_ids_g6_g9.csv",
    )
    n = st.number_input("Num questions", min_value=1, max_value=15, value=3)
    g = st.selectbox("Grade", [6, 7, 8, 9], index=[6, 7, 8, 9].index(grade), key="cq_grade")
    if st.button("Start session"):
        try:
            session = _post(
                "/quizzes/customizable",
                {
                    "student_id": user_id,
                    "grade": g,
                    "chapters": [c.strip() for c in chapter.split(",") if c.strip()],
                    "num_questions": int(n),
                },
            )
            st.session_state.quiz_session = session
            st.session_state.current_q = None
            st.json(session)
        except Exception as exc:
            _api_error(exc)

    session = st.session_state.get("quiz_session")
    if not session:
        return
    sid = session["session_id"]
    col1, col2, col3 = st.columns(3)
    if col1.button("Next question"):
        try:
            st.session_state.current_q = _get(f"/quizzes/{sid}/next")
        except Exception as exc:
            _api_error(exc)
    if col2.button("Results"):
        try:
            st.json(_get(f"/quizzes/{sid}/results"))
        except Exception as exc:
            _api_error(exc)
    if col3.button("Terminate (C3 kill switch)"):
        try:
            st.json(
                _post(
                    f"/quizzes/{sid}/terminate",
                    {"reason": "streamlit_kill", "source": "component_3"},
                )
            )
        except Exception as exc:
            _api_error(exc)

    current = st.session_state.get("current_q")
    if current:
        q = current["question"]
        _render_question_prompt(q)
        answer = st.text_input("Answer (letter / True|False / text)", key="quiz_answer")
        if st.button("Submit answer"):
            try:
                result = _post(
                    f"/quizzes/{sid}/answer",
                    {
                        "question_id": q["id"],
                        "student_answer": answer,
                        "time_taken_seconds": 20.0,
                    },
                )
                st.json(result)
                st.session_state.current_q = None
            except Exception as exc:
                _api_error(exc)


def page_post_lesson(user_id: str, grade: int) -> None:
    st.header("Post-lesson (C1 / C3 sim)")
    chapter = st.text_input("chapter_id", value="G6_C7", key="pl_chapter", help="e.g. G6_C7")
    g = st.selectbox("Grade", [6, 7, 8, 9], index=[6, 7, 8, 9].index(grade), key="pl_grade")
    if st.button("Trigger post-lesson"):
        try:
            session = _post(
                "/quizzes/post-lesson",
                {"student_id": user_id, "chapter_id": chapter, "grade": g},
            )
            st.session_state.quiz_session = session
            st.success(f"session_id={session['session_id']} max={session['max_questions']}")
            st.json(session)
        except Exception as exc:
            _api_error(exc)


def page_history(user_id: str) -> None:
    st.header("Student history")
    try:
        sessions = _get(f"/students/{user_id}/sessions")
    except Exception as exc:
        _api_error(exc)
        return
    st.write(f"{len(sessions)} sessions")
    for item in sessions:
        with st.expander(f"{item['session_kind']} · {item['status']} · {item['session_id'][:8]}"):
            st.json(item)
            if st.button("Detail", key=f"d_{item['session_id']}"):
                try:
                    st.json(_get(f"/students/{user_id}/sessions/{item['session_id']}"))
                except Exception as exc:
                    _api_error(exc)
            if st.button("Analyze", key=f"a_{item['session_id']}"):
                try:
                    st.json(_post(f"/students/{user_id}/sessions/{item['session_id']}/analyze"))
                except Exception as exc:
                    _api_error(exc)


def page_teacher(class_code: str | None) -> None:
    st.header("Teacher dashboard")
    grade = st.selectbox("Grade filter", [None, 6, 7, 8, 9], format_func=lambda x: "all" if x is None else str(x))
    status = st.selectbox("Status", [None, "pending", "approved", "rejected"])
    params: dict[str, Any] = {"limit": 50}
    if grade is not None:
        params["grade"] = grade
    if status:
        params["status"] = status
    if class_code:
        params["class_code"] = class_code
    try:
        data = _get("/teacher/questions", **params)
    except Exception as exc:
        _api_error(exc)
        return
    questions = data.get("questions") or []
    st.write(f"{len(questions)} questions")
    for q in questions[:20]:
        with st.expander(
            f"{q.get('status')} · DOK{q.get('dok_level')} · {q.get('question_type')} · {q.get('id','')[:8]}"
        ):
            st.json(q)
            reason = st.selectbox(
                "Reject reason",
                [
                    "FACTUAL_ERROR",
                    "OUT_OF_SCOPE",
                    "POOR_PHRASING",
                    "TOO_EASY",
                    "TOO_HARD",
                    "OTHER",
                ],
                key=f"r_{q['id']}",
            )
            if st.button("Reject", key=f"rj_{q['id']}"):
                try:
                    st.json(
                        _post(
                            f"/teacher/questions/{q['id']}/reject",
                            {"reason": reason, "notes": "streamlit reject"},
                        )
                    )
                except Exception as exc:
                    _api_error(exc)
            if st.button("Approve", key=f"ap_{q['id']}"):
                try:
                    st.json(_post(f"/teacher/questions/{q['id']}/approve"))
                except Exception as exc:
                    _api_error(exc)


def main() -> None:
    st.set_page_config(page_title="IAE frontend_test", layout="wide")
    if "user_id" not in st.session_state:
        page_login()
        return

    meta = st.session_state.user_meta
    st.sidebar.write(f"**{meta['label']}**")
    st.sidebar.code(st.session_state.user_id)
    if st.sidebar.button("Sign out"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    role = meta["role"]
    grade = int(meta["grade"] or 7)
    if role == "teacher":
        page = st.sidebar.radio("Page", ["Teacher Dashboard", "Post-lesson sim"])
        if page == "Teacher Dashboard":
            page_teacher(meta.get("class_code"))
        else:
            page_post_lesson("mock-student-class-a", 7)
    else:
        page = st.sidebar.radio(
            "Page",
            ["Amplitude", "Customizable Quiz", "Post-lesson", "History"],
        )
        if page == "Amplitude":
            page_amplitude(st.session_state.user_id, grade)
        elif page == "Customizable Quiz":
            page_customizable(st.session_state.user_id, grade)
        elif page == "Post-lesson":
            page_post_lesson(st.session_state.user_id, grade)
        else:
            page_history(st.session_state.user_id)


if __name__ == "__main__":
    main()
