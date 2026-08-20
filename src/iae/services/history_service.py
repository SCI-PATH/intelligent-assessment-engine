"""Student session history + LLM constructive analysis."""

from __future__ import annotations

from typing import Any

from iae.core.models import (
    AttemptRecord,
    MCQPayload,
    MultiBlankPayload,
    Question,
    SessionState,
    ShortAnswerPayload,
    TrueFalsePayload,
)
from iae.core.protocols import ILlmJson
from iae.infrastructure.postgres.questions_repo import PostgresQuestionRepository
from iae.infrastructure.postgres.sessions_repo import PostgresSessionRepository
from iae.prompts import render


def expected_answer(question: Question) -> Any:
    payload = question.payload
    if isinstance(payload, MCQPayload):
        return payload.correct_answer
    if isinstance(payload, ShortAnswerPayload):
        return payload.ideal_answer
    if isinstance(payload, MultiBlankPayload):
        return list(payload.answers)
    if isinstance(payload, TrueFalsePayload):
        return payload.correct_answer
    return None


class HistoryService:
    def __init__(
        self,
        *,
        sessions: PostgresSessionRepository,
        questions: PostgresQuestionRepository,
        llm: ILlmJson | None = None,
    ) -> None:
        self._sessions = sessions
        self._questions = questions
        self._llm = llm

    def list_sessions(self, student_id: str, *, limit: int = 50) -> list[SessionState]:
        return self._sessions.list_for_user(student_id, limit=limit)

    def get_session_detail(self, student_id: str, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None or session.user_id != student_id:
            raise KeyError(session_id)
        items: list[dict[str, Any]] = []
        for attempt in session.history:
            question = self._questions.get(attempt.question_id)
            items.append(
                {
                    "attempt": attempt,
                    "question": question,
                    "expected_answer": expected_answer(question) if question else None,
                    "student_answer": attempt.student_answer,
                }
            )
        return {
            "session": session,
            "items": items,
            "ai_analysis": session.ai_analysis,
        }

    def analyze_session(self, student_id: str, session_id: str) -> dict[str, Any]:
        detail = self.get_session_detail(student_id, session_id)
        session: SessionState = detail["session"]
        wrong: list[AttemptRecord] = [a for a in session.history if not a.is_correct]
        if not wrong:
            analysis = {
                "summary": "All answered items were correct. Keep practising to maintain mastery.",
                "items": [],
            }
            session.ai_analysis = analysis
            self._sessions.update(session)
            return analysis

        item_payloads: list[dict[str, Any]] = []
        for attempt in wrong:
            question = self._questions.get(attempt.question_id)
            item_payloads.append(
                {
                    "question_id": attempt.question_id,
                    "chapter": attempt.chapter_name,
                    "student_answer": attempt.student_answer,
                    "expected": expected_answer(question) if question else None,
                    "feedback": attempt.feedback,
                    "error_category": attempt.error_category,
                }
            )

        if self._llm is None:
            analysis = {
                "summary": "Review the missed items below and revisit the related chapter notes.",
                "items": [
                    {
                        "question_id": item["question_id"],
                        "advice": f"Revisit {item['chapter']}. Your answer differed from the expected response.",
                    }
                    for item in item_payloads
                ],
                "source": "heuristic_fallback",
            }
        else:
            prompt = render(
                "analytics/session_analysis.jinja",
                wrong_items=item_payloads,
                chapter=session.scope_chapter,
                grade=session.grade,
            )
            try:
                raw = self._llm.generate_json(prompt, temperature=0.2)
                analysis = {
                    "summary": str(raw.get("summary") or "Focus on the missed concepts below."),
                    "items": list(raw.get("items") or []),
                    "source": "llm",
                }
            except Exception:
                analysis = {
                    "summary": "Could not reach the analysis model; use the miss list as a study checklist.",
                    "items": [
                        {
                            "question_id": item["question_id"],
                            "advice": f"Revisit {item['chapter']}.",
                        }
                        for item in item_payloads
                    ],
                    "source": "heuristic_fallback",
                }

        session.ai_analysis = analysis
        self._sessions.update(session)
        return analysis
