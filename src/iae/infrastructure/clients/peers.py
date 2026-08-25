"""Peer HTTP helpers with hardcoded mocks beside commented live httpx calls.

Toggle live traffic via ``iae.config.peers.PEER_HTTP_LIVE`` (C1/C3) and
``C4_HTTP_LIVE`` (C4 :8003). Live calls run first; mocks are the fallback.
Mocks use real ``topic_id`` values from ``data/chapter_ids_g6_g9.csv``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from iae.config.peers import (
    C1_ACTIVE_CHAPTER_PATH,
    C1_QUIZ_READY_PATH,
    C3_SESSION_TERMINATED_PATH,
    C4_ASSESSMENT_SUBMIT_PATH,
    C4_BKT_SNAPSHOT_PATH,
    C4_HTTP_LIVE,
    PEER_HTTP_LIVE,
    component_1_base_url,
    component_3_base_url,
    component_4_base_url,
    join_url,
)
from iae.domain.chapter_catalog import get_chapter, load_chapters
from iae.config.settings import get_settings

logger = logging.getLogger(__name__)


def _timeout() -> float:
    return float(get_settings().http_client_timeout_s)


def _csv_topics_for_chapters(chapter_ids: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """Resolve real topic_ids from the Component 4 chapter CSV."""
    topic_ids: list[str] = []
    topics_by_chapter: dict[str, list[str]] = {}
    catalog = load_chapters()
    for cid in chapter_ids:
        record = catalog.get(cid) or get_chapter(cid)
        if record is None:
            topics_by_chapter[cid] = []
            continue
        tids = list(record.topic_ids)
        topics_by_chapter[cid] = tids
        for tid in tids:
            if tid not in topic_ids:
                topic_ids.append(tid)
    return topic_ids, topics_by_chapter


def mock_bkt_snapshot(*, user_id: str, chapter_ids: list[str]) -> dict[str, Any]:
    """Hardcoded Component 4 bkt-snapshot shape with CSV-aligned topic IDs."""
    chapter_ids = [c for c in chapter_ids if c]
    topic_ids, topics_by_chapter = _csv_topics_for_chapters(chapter_ids)
    if not topic_ids:
        # Fallback only if chapter_id is unknown to the CSV (should not happen in prod).
        topic_ids = [f"{cid}_UNKNOWN" for cid in chapter_ids] or ["UNKNOWN"]
        topics_by_chapter = {cid: [f"{cid}_UNKNOWN"] for cid in chapter_ids}
    topic_bkt = {
        tid: {
            "mastery_probability": 0.25,
            "mastery_category": "basic",
            "attempts": 0,
            "seen": False,
        }
        for tid in topic_ids
    }
    return {
        "success": True,
        "user_id": user_id,
        "chapter_ids": list(chapter_ids),
        "unknown_chapter_ids": [],
        "topic_ids": topic_ids,
        "topics_by_chapter": topics_by_chapter,
        "topic_bkt": topic_bkt,
        "mastery_category_thresholds": {
            "basic": "P(L) < 0.50",
            "intermediate": "0.50 <= P(L) < 0.80",
            "advanced": "P(L) >= 0.80",
        },
        "source": "hardcoded_mock",
    }


def mock_assessment_submit(payload: dict[str, Any]) -> dict[str, Any]:
    """Hardcoded Component 4 assessment-submit acknowledgement."""
    topic_id = str(payload.get("topic_id") or "")
    chapter_ids = payload.get("chapter_ids") or []
    topic_bkt: dict[str, Any] = {}
    if topic_id:
        topic_bkt[topic_id] = {
            "mastery_probability": 0.30,
            "mastery_category": "basic",
            "attempts": 1,
            "seen": True,
        }
    return {
        "ok": True,
        "success": True,
        "source": "hardcoded_mock",
        "accepted": payload.get("question_id"),
        "topic_id": topic_id,
        "mastery_category": "basic",
        "updated_mastery_probability": 0.30,
        "mastery_probability": 0.30,
        "chapter_ids": chapter_ids,
        "unknown_chapter_ids": [],
        "topic_bkt": topic_bkt,
    }


class Component4Client:
    """Learner Profile Analytics / BKT (Component 4)."""

    def fetch_bkt_snapshot(self, *, user_id: str, chapter_ids: list[str]) -> dict[str, Any]:
        mock = mock_bkt_snapshot(user_id=user_id, chapter_ids=chapter_ids)

        if not C4_HTTP_LIVE:
            logger.info("C4 bkt-snapshot mock for user=%s chapters=%s", user_id, chapter_ids)
            return mock

        url = join_url(component_4_base_url(), C4_BKT_SNAPSHOT_PATH)
        body = {"user_id": user_id, "chapter_ids": chapter_ids}
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.post(url, json=body)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict):
                    data.setdefault("source", "live")
                    logger.info("C4 bkt-snapshot live ok user=%s chapters=%s", user_id, chapter_ids)
                    return data
        except Exception as exc:
            logger.warning("C4 bkt-snapshot failed (%s) — mock fallback", exc)
        return mock

    def submit_assessment(self, payload: dict[str, Any]) -> dict[str, Any]:
        mock = mock_assessment_submit(payload)

        if not C4_HTTP_LIVE:
            return mock

        url = join_url(component_4_base_url(), C4_ASSESSMENT_SUBMIT_PATH)
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

    def fetch_active_chapter(self, *, student_id: str) -> dict[str, Any]:
        """Return the chapter C1 says this student just finished / is on.

        Expected live response (adjust field names when C1 confirms):
          {
            "student_id": "...",
            "chapter_id": "G6_C8",
            "grade": 6,
            "lesson_id": "optional"
          }
        """
        mock = {
            "ok": True,
            "source": "hardcoded_mock",
            "student_id": student_id,
            "chapter_id": "G6_C8",
            "grade": 6,
            "lesson_id": None,
        }
        # --- HARDCODED MOCK (active while PEER_HTTP_LIVE is False) ---
        if not PEER_HTTP_LIVE:
            logger.info("C1 active-chapter mock for student=%s → %s", student_id, mock["chapter_id"])
            return mock

        # --- LIVE INTEGRATION ---
        url = join_url(component_1_base_url(), C1_ACTIVE_CHAPTER_PATH)
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.get(url, params={"student_id": student_id})
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict) and (data.get("chapter_id") or "").strip():
                    data.setdefault("source", "live")
                    data.setdefault("student_id", student_id)
                    return data
                logger.warning("C1 active-chapter missing chapter_id — mock fallback")
        except Exception as exc:
            logger.warning("C1 active-chapter failed (%s) — mock fallback", exc)
        return mock

        # Example live call:
        # with httpx.Client(timeout=_timeout()) as client:
        #     response = client.get(
        #         join_url(component_1_base_url(), C1_ACTIVE_CHAPTER_PATH),
        #         params={"student_id": student_id},
        #     )
        #     response.raise_for_status()
        #     return response.json()

    def notify_quiz_ready(self, *, student_id: str, chapter_id: str, session_id: str) -> dict[str, Any]:
        mock = {
            "ok": True,
            "source": "hardcoded_mock",
            "student_id": student_id,
            "chapter_id": chapter_id,
            "session_id": session_id,
        }
        # --- HARDCODED MOCK ---
        if not PEER_HTTP_LIVE:
            return mock

        # --- LIVE INTEGRATION ---
        url = join_url(component_1_base_url(), C1_QUIZ_READY_PATH)
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

        # with httpx.Client(timeout=_timeout()):
        #     client.post(
        #         join_url(component_1_base_url(), C1_QUIZ_READY_PATH),
        #         json={"student_id": student_id, "chapter_id": chapter_id, "session_id": session_id},
        #     )


class Component3Client:
    """Engagement / frustration (Component 3)."""

    def notify_session_terminated(self, *, session_id: str, reason: str) -> dict[str, Any]:
        mock = {
            "ok": True,
            "source": "hardcoded_mock",
            "session_id": session_id,
            "reason": reason,
        }
        # --- HARDCODED MOCK ---
        if not PEER_HTTP_LIVE:
            return mock

        # --- LIVE INTEGRATION ---
        url = join_url(component_3_base_url(), C3_SESSION_TERMINATED_PATH)
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

        # with httpx.Client(timeout=_timeout()) as client:
        #     client.post(
        #         join_url(component_3_base_url(), C3_SESSION_TERMINATED_PATH),
        #         json={"session_id": session_id, "reason": reason},
        #     )
