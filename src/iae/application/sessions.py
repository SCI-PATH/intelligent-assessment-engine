"""Use cases for diagnostic sessions.

The service orchestrates the policy, the question repository, and the session
repository; it knows nothing about HTTP, Streamlit, or Mongo specifics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from iae.core.models import (
    AttemptRecord,
    GradeResult,
    Question,
    RlAction,
    RlState,
    SessionState,
)
from iae.core.protocols import (
    IGradingService,
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
    ) -> None:
        self._sessions = sessions
        self._questions = questions
        self._grading = grading
        self._policy = policy
        self._limits = limits

    # ---- lifecycle -------------------------------------------------------------

    def create_session(self, scope_chapter: str) -> SessionState:
        session = SessionState(scope_chapter=scope_chapter)
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

        # Avoid repeating semantically identical prompts (same stem/paragraph),
        # not just duplicate question IDs.
        excluded_ids = list(session.used_question_ids)
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
        self._sessions.update(session)

        from iae.adaptive.telemetry import rolling_accuracy

        return NextQuestion(
            question=question,
            action=action,
            state=state,
            rolling_accuracy=rolling_accuracy(session.history, self._limits.rolling_window),
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

        result = self._grading.grade(question, student_answer)
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
            time_taken_seconds=time_taken_seconds,
        )
        session.history.append(attempt)
        session.questions_asked += 1
        self._sessions.update(session)
        return result, session

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
            accuracy_score=last.accuracy_score,
            streak=current_streak(session.history),
            current_difficulty=last.dok_level,
            current_sub_concept="ChapterWide",
        )


