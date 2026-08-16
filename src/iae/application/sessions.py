"""Use cases for diagnostic sessions.

The service orchestrates the policy, the question repository, and the session
repository; it knows nothing about HTTP, Streamlit, or storage specifics.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

from iae.core.models import (
    AttemptRecord,
    GradeResult,
    Question,
    RlAction,
    RlState,
    SessionState,
)
from iae.application.analytics_payload import build_analytics_payload, send_analytics_event
from iae.core.protocols import (
    IAnalyticsRepository,
    IEmbedder,
    IGradingService,
    ILlmJson,
    IQuestionRepository,
    IRlPolicy,
    ISessionRepository,
)


class NoQuestionAvailable(RuntimeError):
    """Raised when the question bank cannot satisfy a relaxed query."""


class NextQuestion(NamedTuple):
    question: Question
    action: RlAction
    state: RlState
    rolling_accuracy: float


_DEBUG_LOG_PATH = Path("debug-21ced4.log")


def _debug_log(*, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "sessionId": "21ced4",
        "runId": "initial",
        "hypothesisId": hypothesis_id,
        "id": f"log_{uuid4().hex}",
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass


@dataclass
class SessionLimits:
    max_questions: int
    rolling_window: int
    response_time_target_seconds: float


class SessionService:
    def __init__(
        self,
        *,
        sessions: ISessionRepository,
        questions: IQuestionRepository,
        grading: IGradingService,
        policy: IRlPolicy,
        limits: SessionLimits,
        analytics: IAnalyticsRepository | None = None,
        embedder: IEmbedder | None = None,
        analytics_llm: ILlmJson | None = None,
    ) -> None:
        self._sessions = sessions
        self._questions = questions
        self._grading = grading
        self._policy = policy
        self._limits = limits
        self._analytics = analytics
        self._embedder = embedder
        self._analytics_llm = analytics_llm

    # ---- lifecycle -------------------------------------------------------------

    def create_session(
        self,
        scope_chapter: str,
        user_id: str | None = None,
        grade: int = 6,
    ) -> SessionState:
        session = SessionState(
            scope_chapter=scope_chapter,
            user_id=(user_id or "").strip() or str(uuid4()),
            grade=grade,
            max_questions=self._limits.max_questions,
        )
        return self._sessions.create(session)

    def get_session(self, session_id: str) -> SessionState:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    # ---- next question ---------------------------------------------------------

    def next_question(self, session_id: str) -> NextQuestion:
        session = self.get_session(session_id)
        if session.questions_asked >= self._limits.max_questions:
            raise NoQuestionAvailable("Session has reached its question limit.")

        if session.last_state is None or session.last_action is None:
            action = self._policy.cold_start_action(session.scope_chapter)
            state = RlState(
                current_chapter=session.scope_chapter,
                current_difficulty=action.next_difficulty_level,
                current_sub_concept=action.next_sub_concept,
            )
        else:
            state = self._derive_state(session)
            action = self._policy.next_action(state, session.history)

        # #region agent log
        _debug_log(
            hypothesis_id="H2",
            location="src/iae/application/sessions.py:next_question",
            message="State and action before repository fetch",
            data={
                "session_id": session_id,
                "questions_asked": session.questions_asked,
                "state_current_difficulty": state.current_difficulty,
                "state_accuracy_score": state.accuracy_score,
                "state_time_taken": state.time_taken,
                "state_streak": state.streak,
                "action_next_difficulty_level": action.next_difficulty_level,
                "action_question_type": action.next_question_type.value,
            },
        )
        # #endregion

        # Never re-serve a question this user has already seen (any session),
        # and also skip near-duplicate stems within the current session.
        excluded_ids = list(
            dict.fromkeys(list(session.used_question_ids) + self._sessions.served_question_ids(session.user_id))
        )
        seen_signatures = set(session.asked_signatures)
        question = None
        for _ in range(12):
            candidate = self._questions.find_one_unused(
                chapter_name=action.target_chapter,
                sub_concept=action.next_sub_concept,
                dok_level=action.next_difficulty_level,
                question_type=action.next_question_type,
                excluded_ids=excluded_ids,
            )
            if candidate is None:
                break
            signature = self._question_signature(candidate)
            if signature not in seen_signatures:
                question = candidate
                break
            excluded_ids.append(candidate.id)
        if question is None:
            raise NoQuestionAvailable(
                "Question bank exhausted for this chapter; run scripts/generate_bank.py."
            )

        session.last_state = state
        session.last_action = action
        session.used_question_ids.append(question.id)
        session.asked_signatures.append(self._question_signature(question))
        self._sessions.mark_served(
            user_id=session.user_id,
            question_id=question.id,
            session_id=session.session_id,
            topic_id=question.topic_id,
            source="bank",
        )
        self._sessions.update(session)

        # #region agent log
        _debug_log(
            hypothesis_id="H3",
            location="src/iae/application/sessions.py:next_question",
            message="Selected question after repository fetch",
            data={
                "session_id": session_id,
                "selected_question_id": question.id,
                "selected_question_type": question.question_type.value,
                "selected_dok_level": question.dok_level,
                "selected_chapter": question.chapter_name,
            },
        )
        # #endregion

        from iae.adaptive.telemetry import rolling_accuracy

        rolling = rolling_accuracy(session.history, self._limits.rolling_window)
        # #region agent log
        _debug_log(
            hypothesis_id="H2",
            location="src/iae/application/sessions.py:next_question",
            message="Computed rolling accuracy for next question",
            data={
                "session_id": session_id,
                "questions_asked": session.questions_asked,
                "history_len": len(session.history),
                "rolling_accuracy": rolling,
                "last_attempt_is_correct": session.history[-1].is_correct if session.history else None,
                "last_attempt_score": session.history[-1].accuracy_score if session.history else None,
            },
        )
        # #endregion
        return NextQuestion(
            question=question,
            action=action,
            state=state,
            rolling_accuracy=rolling,
        )

    @staticmethod
    def _question_signature(question: Question) -> str:
        payload = question.payload
        if hasattr(payload, "question"):
            text = getattr(payload, "question")
        else:
            text = getattr(payload, "paragraph", "")
        # Looser signature: chapter + normalized stem only, so near-duplicates
        # generated from slightly different wording still dedupe within a session.
        normalized = " ".join(str(text).lower().split())[:120]
        return f"{question.chapter_name}|{normalized}"


    # ---- submission ------------------------------------------------------------

    def submit_answer(
        self,
        session_id: str,
        question_id: str,
        student_answer: str,
        time_taken_seconds: float,
    ) -> tuple[GradeResult, SessionState]:
        session = self.get_session(session_id)
        question = self._questions.get(question_id)
        if question is None:
            raise KeyError(question_id)
        from iae.adaptive.telemetry import rolling_accuracy

        action = session.last_action
        state = session.last_state
        rolling_at_decision = rolling_accuracy(session.history, self._limits.rolling_window)

        result = self._grading.grade(question, student_answer)
        # #region agent log
        _debug_log(
            hypothesis_id="H3",
            location="src/iae/application/sessions.py:submit_answer",
            message="Submit answer grading result",
            data={
                "session_id": session_id,
                "question_id": question.id,
                "question_type": question.question_type.value,
                "student_answer": student_answer,
                "grade_is_correct": result.is_correct,
                "grade_accuracy_score": result.accuracy_score,
            },
        )
        # #endregion
        attempt = AttemptRecord(
            question_id=question.id,
            question_type=question.question_type,
            chapter_name=question.chapter_name,
            sub_concept="ChapterWide",
            dok_level=question.dok_level,
            student_answer=student_answer,
            accuracy_score=result.accuracy_score,
            is_correct=result.is_correct,
            feedback=result.feedback,
            reasoning=result.reasoning,
            error_category=result.error_category,
            missing_keywords=result.missing_keywords,
            detailed_explanation=result.detailed_explanation,
            missed_blanks=result.missed_blanks,
            concept_explanation=result.concept_explanation,
            distractor_tag=result.distractor_tag,
            distractor_label=result.distractor_label,
            adaptive_decision=(
                f"{(action.dok_summary if action else '').strip()} | "
                f"{(action.type_summary if action else '').strip()}"
            ).strip(" |"),
            decision_rule_triggered=(action.rule_triggered if action else ""),
            decision_dok_reason=(action.dok_reason if action else ""),
            decision_question_type_reason=(action.question_type_reason if action else ""),
            decision_dok_trace=(action.dok_trace if action else None),
            decision_type_trace=(action.type_trace if action else None),
            decision_prev_dok=(state.current_difficulty if state else None),
            decision_target_dok=(action.next_difficulty_level if action else None),
            decision_rolling_accuracy=rolling_at_decision,
            decision_last_accuracy=(state.accuracy_score if state else None),
            decision_last_response_time_seconds=time_taken_seconds,
            time_taken_seconds=time_taken_seconds,
        )
        session.history.append(attempt)
        session.questions_asked += 1
        payload = self._record_analytics(
            session,
            question,
            result,
            student_answer,
            time_taken_seconds=time_taken_seconds,
        )
        self._sessions.record_attempt(
            attempt,
            user_id=session.user_id,
            session_id=session.session_id,
            topic_id=question.topic_id,
            similarity_score=payload.get("similarity_score") if payload else None,
            distractor_tag=payload.get("distractor_tag") if payload else None,
            distractor_label=payload.get("distractor_label") if payload else None,
        )
        # #region agent log
        _debug_log(
            hypothesis_id="H4",
            location="src/iae/application/sessions.py:submit_answer",
            message="Session history updated after grading",
            data={
                "session_id": session_id,
                "new_questions_asked": session.questions_asked,
                "history_len": len(session.history),
                "last_history_is_correct": session.history[-1].is_correct,
                "last_history_accuracy_score": session.history[-1].accuracy_score,
            },
        )
        # #endregion
        self._sessions.update(session)
        return result, session

    def _record_analytics(
        self,
        session: SessionState,
        question: Question,
        result: GradeResult,
        student_answer: str,
        *,
        time_taken_seconds: float = 0.0,
    ) -> dict:
        payload = build_analytics_payload(
            user_id=session.user_id,
            question=question,
            grade=result,
            student_answer=student_answer,
            response_time_s=time_taken_seconds,
            embedder=self._embedder,
            llm=self._analytics_llm,
        )
        if self._analytics is not None:
            try:
                self._analytics.insert(payload, session_id=session.session_id)
            except Exception:
                pass
        send_analytics_event(payload)
        return payload

    # ---- internal --------------------------------------------------------------

    def _derive_state(self, session: SessionState) -> RlState:
        last = session.history[-1]
        from iae.adaptive.telemetry import current_streak

        # Policy thresholds are defined on normalized response time [0, 1+].
        normalized_time = min(
            max(last.time_taken_seconds / self._limits.response_time_target_seconds, 0.0),
            2.0,
        )

        return RlState(
            current_chapter=session.scope_chapter,
            time_taken=normalized_time,
            response_time_seconds=last.time_taken_seconds,
            accuracy_score=last.accuracy_score,
            streak=current_streak(session.history),
            current_difficulty=last.dok_level,
            last_question_type=last.question_type,
            current_sub_concept="ChapterWide",
        )


