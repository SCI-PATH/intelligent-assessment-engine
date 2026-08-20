"""HTTP clients for peer microservices with resilient mock fallbacks.

Component 4 contract (see ``docs/QuestionEngine-BKT-Snapshot.md``):
  - Quiz start: ``POST /api/v1/quiz/bkt-snapshot`` with ``user_id`` + ``chapter_ids``
  - Each answer: ``POST /api/v1/assessment-submit`` (optional ``chapter_ids``)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from iae.core.settings import get_settings

logger = logging.getLogger(__name__)


def _timeout() -> float:
    return float(get_settings().http_client_timeout_s)


def _mock_topic_bkt(topic_ids: list[str]) -> dict[str, Any]:
    topic_bkt: dict[str, Any] = {}
    for tid in topic_ids:
        topic_bkt[tid] = {
            "mastery_probability": 0.25,
            "mastery_category": "basic",
            "attempts": 0,
            "seen": False,
        }
    return topic_bkt


class Component4Client:
    """Learner Profile Analytics / BKT (Component 4)."""

    def fetch_bkt_snapshot(
        self,
        *,
        user_id: str,
        chapter_ids: list[str],
    ) -> dict[str, Any]:
        """Read-only quiz-start snapshot. Never raises into the quiz loop."""
        chapter_ids = [c for c in chapter_ids if c]
        mock_topics = [f"{cid}_TOPIC" for cid in chapter_ids] or ["UNKNOWN"]
        mock = {
            "success": True,
            "user_id": user_id,
            "chapter_ids": list(chapter_ids),
            "unknown_chapter_ids": [],
            "topic_ids": mock_topics,
            "topics_by_chapter": {cid: [f"{cid}_TOPIC"] for cid in chapter_ids},
            "topic_bkt": _mock_topic_bkt(mock_topics),
            "mastery_category_thresholds": {
                "basic": "P(L) < 0.50",
                "intermediate": "0.50 <= P(L) < 0.80",
                "advanced": "P(L) >= 0.80",
            },
            "source": "mock_fallback",
        }
        base = get_settings().c4_base_url
        if not base:
            logger.warning("COMPONENT_4_URL empty — using BKT snapshot mock for %s", user_id)
            return mock

        url = f"{base}/api/v1/quiz/bkt-snapshot"
        body = {"user_id": user_id, "chapter_ids": chapter_ids}
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.post(url, json=body)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict):
                    data.setdefault("source", "live")
                    return data
        except Exception as exc:
            logger.warning("C4 bkt-snapshot failed (%s) — mock fallback", exc)
        return mock

    def submit_assessment(self, payload: dict[str, Any]) -> dict[str, Any]:
        base = get_settings().c4_base_url
        mock = {
            "ok": True,
            "success": True,
            "source": "mock_fallback",
            "accepted": payload.get("question_id"),
            "topic_id": payload.get("topic_id"),
            "mastery_category": "basic",
            "updated_mastery_probability": 0.30,
            "mastery_probability": 0.30,
            "chapter_ids": payload.get("chapter_ids") or [],
            "unknown_chapter_ids": [],
            "topic_bkt": {},
        }
        if not base:
            logger.warning("COMPONENT_4_URL empty — skipping assessment-submit (mock ok)")
            return mock
        url = f"{base}/api/v1/assessment-submit"
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json() if response.content else {"ok": True}
                if isinstance(data, dict):
                    data.setdefault("source", "live")
                    return data
                return {"ok": True, "source": "live"}
        except Exception as exc:
            logger.warning("C4 assessment-submit failed (%s) — mock fallback", exc)
            return mock


class Component1Client:
    """Lesson Engine (Component 1)."""

    def notify_quiz_ready(self, *, student_id: str, chapter_id: str, session_id: str) -> dict[str, Any]:
        base = get_settings().component_1_url.rstrip("/")
        mock = {
            "ok": True,
            "source": "mock_fallback",
            "student_id": student_id,
            "chapter_id": chapter_id,
            "session_id": session_id,
        }
        if not base:
            return mock
        url = f"{base}/api/v1/lessons/quiz-ready"
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.post(
                    url,
                    json={
                        "student_id": student_id,
                        "chapter_id": chapter_id,
                        "session_id": session_id,
                    },
                )
                response.raise_for_status()
                data = response.json() if response.content else {"ok": True}
                if isinstance(data, dict):
                    data.setdefault("source", "live")
                    return data
        except Exception as exc:
            logger.warning("C1 notify failed (%s) — mock fallback", exc)
        return mock


class Component3Client:
    """Engagement / frustration (Component 3)."""

    def notify_session_terminated(self, *, session_id: str, reason: str) -> dict[str, Any]:
        base = get_settings().component_3_url.rstrip("/")
        mock = {"ok": True, "source": "mock_fallback", "session_id": session_id, "reason": reason}
        if not base:
            return mock
        url = f"{base}/api/v1/engagement/session-terminated"
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.post(url, json={"session_id": session_id, "reason": reason})
                response.raise_for_status()
                data = response.json() if response.content else {"ok": True}
                if isinstance(data, dict):
                    data.setdefault("source", "live")
                    return data
        except Exception as exc:
            logger.warning("C3 notify failed (%s) — mock fallback", exc)
        return mock
