"""Peer HTTP helpers with hardcoded mocks beside commented live httpx calls.

Toggle live traffic via ``iae.config.peers.PEER_HTTP_LIVE`` (C3),
``C1_HTTP_LIVE`` (C1 :8000), and ``C4_HTTP_LIVE`` (C4 :8003).
Live calls run first; mocks are the fallback.
Mocks use real ``topic_id`` values from ``data/chapter_ids_g6_g9.csv``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from iae.config.peers import (
    C1_ACTIVE_CHAPTER_PATH,
    C1_HTTP_LIVE,
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
from iae.domain.chapter_catalog import (
    chapter_id_from_c1_lesson_id,
    chapter_id_from_grade_and_number,
    get_chapter,
    load_chapters,
    normalize_chapter_id,
    parse_c1_lesson_id,
)
from iae.config.settings import get_settings

logger = logging.getLogger(__name__)

_FALLBACK_CHAPTER_NUMBER = 8
_FALLBACK_GRADE = 6


def _timeout() -> float:
    return float(get_settings().http_client_timeout_s)


def _fallback_chapter_id(grade: int | None = None) -> tuple[str, int]:
    """Grade-aware offline stub: ``G{g}_C8`` (defaults grade 6 → G6_C8)."""
    g = int(grade) if grade in (6, 7, 8, 9) else _FALLBACK_GRADE
    cid = chapter_id_from_grade_and_number(g, _FALLBACK_CHAPTER_NUMBER) or f"G{g}_C{_FALLBACK_CHAPTER_NUMBER}"
    return cid, g


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


def _c1_active_chapter_mock(
    *,
    student_id: str,
    grade: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    cid, g = _fallback_chapter_id(grade)
    out: dict[str, Any] = {
        "ok": True,
        "source": "fallback",
        "student_id": student_id,
        "chapter_id": cid,
        "grade": g,
        "lesson_id": None,
    }
    if error:
        out["error"] = error
    return out


def _map_c1_progress_to_chapter(data: dict[str, Any]) -> tuple[str, int, str | None] | None:
    """Map C1 ``GET /progress`` JSON → ``(canonical_chapter_id, grade, lesson_id)``.

    Prefer the lesson *just finished* for post-lesson quizzes:
    after a passing quiz C1 advances ``current_lesson_id``, so the finished
    chapter is usually the previous one (and present in ``completed_lesson_ids``).
    """
    completed_raw = data.get("completed_lesson_ids") or []
    completed: list[str] = [
        x.strip() for x in completed_raw if isinstance(x, str) and x.strip()
    ]

    current_id: str | None = None
    raw_current = data.get("current_lesson_id")
    if isinstance(raw_current, str) and raw_current.strip():
        current_id = raw_current.strip()

    lesson_id: str | None = None

    # 1) Just-finished = previous chapter vs current (typical post-lesson handoff).
    current_parsed = parse_c1_lesson_id(current_id) if current_id else None
    if current_parsed is not None:
        grade_c, chapter_c = current_parsed
        if chapter_c > 1:
            want = (grade_c, chapter_c - 1)
            for lid in reversed(completed):
                if parse_c1_lesson_id(lid) == want:
                    lesson_id = lid
                    break
            if lesson_id is None:
                # C1 may not have appended yet; still target previous chapter id.
                lesson_id = f"g{grade_c}_sci_{chapter_c - 1:02d}"

    # 2) Last completed lesson (append order).
    if not lesson_id and completed:
        lesson_id = completed[-1]

    # 3) Current lesson.
    if not lesson_id and current_id:
        lesson_id = current_id

    grade: int | None = None
    raw_grade = data.get("grade")
    if raw_grade is not None:
        try:
            grade = int(raw_grade)
        except (TypeError, ValueError):
            grade = None

    chapter_number: int | None = None
    raw_chapter = data.get("chapter_number")
    if raw_chapter is not None:
        try:
            chapter_number = int(raw_chapter)
        except (TypeError, ValueError):
            chapter_number = None

    # Prefer grade/chapter derived from the chosen lesson_id.
    parsed = parse_c1_lesson_id(lesson_id) if lesson_id else None
    if parsed is not None:
        grade = parsed[0]
        chapter_number = parsed[1]

    cid: str | None = None
    if lesson_id:
        cid = chapter_id_from_c1_lesson_id(lesson_id)
    if not cid and grade is not None and chapter_number is not None:
        cid = chapter_id_from_grade_and_number(grade, chapter_number)

    if not cid:
        return None

    normalized = normalize_chapter_id(cid, grade=grade)
    if not normalized:
        return None

    resolved_grade = grade if grade is not None else _FALLBACK_GRADE
    record = get_chapter(normalized)
    if record is not None:
        resolved_grade = record.grade

    return normalized, resolved_grade, lesson_id


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

    def fetch_active_chapter(
        self,
        *,
        student_id: str,
        grade: int | None = None,
    ) -> dict[str, Any]:
        """Resolve the chapter for post-lesson quiz scoping.

        Live: ``GET {COMPONENT_1_URL}/progress?user_id=`` then map C1 lesson
        identity (``g6_sci_03`` / grade+chapter_number) → canonical ``G6_C3``.
        Prefers the lesson just finished for post-lesson handoff.

        Always returns a usable dict; never raises. On live-off / timeout /
        HTTP / parse failure → grade-aware ``G{g}_C8`` fallback
        (``source=fallback``). Live success uses ``source=component_1``.
        """
        mock = _c1_active_chapter_mock(student_id=student_id, grade=grade)
        if not C1_HTTP_LIVE:
            logger.info(
                "C1 active-chapter fallback (C1_HTTP_LIVE=False) student=%s → %s",
                student_id,
                mock["chapter_id"],
            )
            return mock

        url = join_url(component_1_base_url(), C1_ACTIVE_CHAPTER_PATH)
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.get(url, params={"user_id": student_id})
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict):
                err = "C1 /progress non-object body"
                logger.warning("%s student=%s — fallback %s", err, student_id, mock["chapter_id"])
                return _c1_active_chapter_mock(student_id=student_id, grade=grade, error=err)

            mapped = _map_c1_progress_to_chapter(data)
            if mapped is None:
                err = "C1 /progress could not map chapter"
                logger.warning("%s student=%s — fallback %s", err, student_id, mock["chapter_id"])
                return _c1_active_chapter_mock(student_id=student_id, grade=grade, error=err)

            chapter_id, resolved_grade, lesson_id = mapped
            logger.info(
                "C1 active-chapter live student=%s → %s (lesson=%s grade=%s)",
                student_id,
                chapter_id,
                lesson_id,
                resolved_grade,
            )
            return {
                "ok": True,
                "source": "component_1",
                "student_id": student_id,
                "chapter_id": chapter_id,
                "grade": resolved_grade,
                "lesson_id": lesson_id,
            }
        except Exception as exc:
            err = str(exc)
            logger.warning(
                "C1 active-chapter failed student=%s err=%s — fallback %s",
                student_id,
                err,
                mock["chapter_id"],
            )
            return _c1_active_chapter_mock(student_id=student_id, grade=grade, error=err)

    def notify_quiz_ready(self, *, student_id: str, chapter_id: str, session_id: str) -> dict[str, Any]:
        """Best-effort notify; C1 may not expose quiz-ready — never fail the quiz."""
        mock = {
            "ok": True,
            "source": "hardcoded_mock",
            "student_id": student_id,
            "chapter_id": chapter_id,
            "session_id": session_id,
        }
        if not C1_HTTP_LIVE:
            return mock

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
