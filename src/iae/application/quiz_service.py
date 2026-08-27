"""Customizable / post-lesson quiz sessions with Time-Discounted Elo DDA.

Component 4 BKT is session-memory only (see QuestionEngine-BKT-Snapshot.md):
refresh at quiz start and after every assessment-submit response.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import uuid4

from iae.domain.chapter_catalog import (
    bank_chapter_names,
    get_chapter,
    normalize_chapter_id,
    resolve_chapter_ids,
)
from iae.domain.exceptions import NoQuestionAvailable
from iae.domain.models import (
    AttemptRecord,
    Question,
    QuestionType,
    SessionKind,
    SessionState,
    SessionStatus,
)
from iae.domain.protocols import ILlmJson
from iae.config.settings import get_config
from iae.application.analytics_payload import build_analytics_payload
from iae.application.grading import GradingService
from iae.infrastructure.clients import (
    Component1Client,
    Component3Client,
    Component4Client,
)
from iae.adaptive import select_next_item, update_elo
from iae.infrastructure.postgres.analytics_repo import PostgresAnalyticsRepository
from iae.infrastructure.postgres.questions_repo import PostgresQuestionRepository
from iae.infrastructure.postgres.sessions_repo import PostgresSessionRepository
from iae.infrastructure.rag.embeddings import HuggingFaceEmbedder

_PASS_THRESHOLD = 0.8
logger = logging.getLogger(__name__)

# Game / FE often stubs chapter 8 when it does not know the real lesson chapter.
_CLIENT_FALLBACK_CHAPTER_RE = re.compile(r"^G([6-9])_C8$", re.IGNORECASE)


def _is_client_fallback_chapter_id(chapter_id: str | None, *, grade: int | None = None) -> bool:
    """True when ``chapter_id`` looks like the client stub ``G{grade}_C8``.

    Resolution rule (post-lesson):
      - omit ``chapter_id`` → always ask Component 1
      - ``G{g}_C8`` with no lesson proof → treat as untrusted stub; prefer live C1
      - any other canonical chapter (e.g. ``G7_C2``) → trust the request body
    """
    raw = (chapter_id or "").strip()
    if not raw:
        return False
    normalized = normalize_chapter_id(raw, grade=grade) or raw.upper().replace("-", "_")
    match = _CLIENT_FALLBACK_CHAPTER_RE.match(normalized)
    if not match:
        return False
    stub_grade = int(match.group(1))
    if grade is not None and int(grade) != stub_grade:
        # e.g. body grade=7 but chapter_id=G6_C8 — still treat as stub noise.
        return True
    return True


def _normalize_c1_source(raw: Any) -> str:
    """Map C1 client source tags → request | component_1 | fallback."""
    text = str(raw or "").strip().lower()
    if text in ("live", "component_1", "c1"):
        return "component_1"
    if text in ("fallback", "hardcoded_mock", "mock"):
        return "fallback"
    return text or "fallback"


def _elo_from_bkt_snapshot(bkt: dict[str, Any]) -> float:
    """Seed Elo from average topic mastery_probability when present."""
    topic_bkt = bkt.get("topic_bkt") if isinstance(bkt, dict) else None
    if isinstance(topic_bkt, dict) and topic_bkt:
        probs: list[float] = []
        for row in topic_bkt.values():
            if isinstance(row, dict) and "mastery_probability" in row:
                try:
                    probs.append(float(row["mastery_probability"]))
                except (TypeError, ValueError):
                    continue
        if probs:
            avg = sum(probs) / len(probs)
            return 800.0 + avg * 600.0
    try:
        return 800.0 + float(bkt.get("p_l", 0.35)) * 600.0
    except (TypeError, ValueError, AttributeError):
        return 1000.0


class QuizService:
    def __init__(
        self,
        *,
        sessions: PostgresSessionRepository,
        questions: PostgresQuestionRepository,
        grading: GradingService,
        analytics: PostgresAnalyticsRepository | None = None,
        embedder: HuggingFaceEmbedder | None = None,
        analytics_llm: ILlmJson | None = None,
        c4: Component4Client | None = None,
        c1: Component1Client | None = None,
        c3: Component3Client | None = None,
    ) -> None:
        self._sessions = sessions
        self._questions = questions
        self._grading = grading
        self._analytics = analytics
        self._embedder = embedder
        self._analytics_llm = analytics_llm
        self._c4 = c4 or Component4Client()
        self._c1 = c1 or Component1Client()
        self._c3 = c3 or Component3Client()

    def create_customizable(
        self,
        *,
        user_id: str,
        grade: int,
        chapters: list[str],
        num_questions: int,
        question_types: list[QuestionType] | None = None,
    ) -> SessionState:
        if not chapters:
            raise ValueError("At least one chapter is required.")
        chapter_ids = resolve_chapter_ids(chapters, grade=grade)
        if not chapter_ids:
            raise ValueError(
                "chapters must be canonical chapter_ids from data/chapter_ids_g6_g9.csv "
                "(e.g. G6_C8) or matching chapter titles."
            )
        types = question_types or list(QuestionType)
        bkt = self._c4.fetch_bkt_snapshot(user_id=user_id, chapter_ids=chapter_ids)
        state = SessionState(
            session_id=str(uuid4()),
            user_id=user_id,
            scope_chapter=chapter_ids[0],
            scope_chapters=list(chapter_ids),
            grade=grade,
            max_questions=max(1, min(int(num_questions), 30)),
            session_kind=SessionKind.CUSTOMIZABLE,
            status=SessionStatus.ACTIVE,
            allowed_question_types=types,
            elo_rating=_elo_from_bkt_snapshot(bkt),
            bkt_snapshot=bkt,
        )
        return self._sessions.create(state)

    def resolve_post_lesson_chapter(
        self,
        *,
        student_id: str,
        chapter_id: str | None = None,
        grade: int | None = None,
    ) -> dict:
        """Resolve chapter for post-lesson quiz scoping.

        Priority:
          1. Live Component 1 when ``chapter_id`` is omitted **or** looks like the
             client stub ``G{grade}_C8`` (no lesson proof) — common Game/FE fallback.
          2. Explicit non-stub ``chapter_id`` from the request body (trusted).
          3. Grade-aware C1 mock (``G{g}_C8``) only when C1 HTTP/parse/map fails
             or ``C1_HTTP_LIVE`` is off.

        Returned ``source`` is one of: ``request`` | ``component_1`` | ``fallback``.
        """
        raw_request = (chapter_id or "").strip()
        resolved_grade = grade
        lesson_id: str | None = None
        source = "request"
        raw = raw_request

        consult_c1 = (not raw_request) or _is_client_fallback_chapter_id(
            raw_request, grade=grade
        )

        if consult_c1:
            try:
                ctx = self._c1.fetch_active_chapter(
                    student_id=student_id,
                    grade=grade,
                )
            except Exception as exc:
                # Client is documented never to raise; still guard.
                logger.warning(
                    "post-lesson C1 resolve raised student_id=%s err=%s",
                    student_id,
                    exc,
                )
                ctx = {
                    "chapter_id": "",
                    "grade": grade,
                    "lesson_id": None,
                    "source": "fallback",
                    "error": str(exc),
                }

            c1_source = _normalize_c1_source(ctx.get("source"))
            c1_raw = str(ctx.get("chapter_id") or "").strip()
            lesson_id = ctx.get("lesson_id")
            if lesson_id is not None:
                lesson_id = str(lesson_id).strip() or None
            c1_error = ctx.get("error")

            if resolved_grade is None and ctx.get("grade") is not None:
                try:
                    resolved_grade = int(ctx["grade"])
                except (TypeError, ValueError):
                    resolved_grade = None

            if c1_source == "component_1" and c1_raw:
                # Live C1 wins over omitted / stub body chapter_id.
                raw = c1_raw
                source = "component_1"
                if ctx.get("grade") is not None:
                    try:
                        resolved_grade = int(ctx["grade"])
                    except (TypeError, ValueError):
                        pass
            elif c1_raw:
                # C1 offline / unmappable → grade-aware fallback only.
                raw = c1_raw
                source = "fallback"
                if resolved_grade is None and ctx.get("grade") is not None:
                    try:
                        resolved_grade = int(ctx["grade"])
                    except (TypeError, ValueError):
                        pass
            elif raw_request and not _is_client_fallback_chapter_id(raw_request, grade=grade):
                raw = raw_request
                source = "request"
            else:
                logger.error(
                    "post-lesson resolve failed student_id=%s request_chapter=%s "
                    "c1_source=%s c1_error=%s",
                    student_id,
                    raw_request or None,
                    c1_source,
                    c1_error,
                )
                raise ValueError(
                    "chapter_id is required (pass a real chapter_id or ensure C1 /progress returns one)."
                )

            logger.info(
                "post-lesson chapter resolve student_id=%s request_chapter=%s "
                "resolved=%s grade=%s source=%s lesson_id=%s c1_source=%s c1_error=%s",
                student_id,
                raw_request or None,
                raw,
                resolved_grade,
                source,
                lesson_id,
                c1_source,
                c1_error,
            )
        else:
            # Trusted explicit chapter from body (not the G*_C8 stub).
            source = "request"
            logger.info(
                "post-lesson chapter resolve student_id=%s request_chapter=%s "
                "resolved=%s grade=%s source=request lesson_id=None "
                "(trusted body; skipped C1)",
                student_id,
                raw_request,
                raw_request,
                resolved_grade,
            )

        if not raw:
            raise ValueError(
                "chapter_id is required (pass it in the body or ensure C1 active-chapter returns one)."
            )
        g = resolved_grade if resolved_grade is not None else 6
        cid = normalize_chapter_id(raw, grade=g) or raw
        record = get_chapter(cid)
        if record is not None:
            g = record.grade
        return {
            "chapter_id": cid,
            "grade": g,
            "source": source,
            "lesson_id": lesson_id,
            "student_id": student_id,
        }

    def trigger_post_lesson(
        self,
        *,
        student_id: str,
        chapter_id: str | None = None,
        grade: int | None = 6,
    ) -> SessionState:
        config = get_config()
        resolved = self.resolve_post_lesson_chapter(
            student_id=student_id,
            chapter_id=chapter_id,
            grade=grade,
        )
        cid = resolved["chapter_id"]
        g = int(resolved["grade"])
        logger.info(
            "trigger_post_lesson student_id=%s chapter_id=%s grade=%s source=%s lesson_id=%s",
            student_id,
            cid,
            g,
            resolved.get("source"),
            resolved.get("lesson_id"),
        )
        bkt = self._c4.fetch_bkt_snapshot(user_id=student_id, chapter_ids=[cid])
        state = SessionState(
            session_id=str(uuid4()),
            user_id=student_id,
            scope_chapter=cid,
            scope_chapters=[cid],
            grade=g,
            max_questions=config.post_lesson_max_questions,
            session_kind=SessionKind.POST_LESSON,
            status=SessionStatus.ACTIVE,
            allowed_question_types=list(QuestionType),
            elo_rating=_elo_from_bkt_snapshot(bkt),
            bkt_snapshot=bkt,
        )
        created = self._sessions.create(state)
        self._c1.notify_quiz_ready(
            student_id=student_id,
            chapter_id=cid,
            session_id=created.session_id,
        )
        return created

    def terminate(self, session_id: str, *, reason: str = "component_3_kill_switch") -> SessionState:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session.status != SessionStatus.ACTIVE:
            return session
        session.status = SessionStatus.TERMINATED
        session.terminate_reason = reason
        self._sessions.update(session)
        self._c3.notify_session_terminated(session_id=session_id, reason=reason)
        return session

    def _find_question(
        self,
        *,
        bank_chapters: list[str],
        types: list[QuestionType],
        target_dok: int,
        excluded_ids: list[str],
        topic_id: str = "",
        preferred_type: QuestionType | None = None,
        exclude_sub_concepts: list[str] | None = None,
    ) -> Question | None:
        ordered_types = list(types)
        if preferred_type and preferred_type in ordered_types:
            ordered_types = [preferred_type] + [t for t in ordered_types if t != preferred_type]
        blocked_subs = exclude_sub_concepts

        # Prefer exact topic + preferred type + target DOK.
        for chapter in bank_chapters:
            for qtype in ordered_types:
                question = self._questions.find_one_unused(
                    chapter_name=chapter,
                    sub_concept="",
                    dok_level=target_dok,
                    question_type=qtype,
                    excluded_ids=excluded_ids,
                    topic_id=topic_id,
                    exclude_sub_concepts=blocked_subs,
                )
                if question:
                    return question

        # DOK fallbacks, still preferring topic_id when set.
        for chapter in bank_chapters:
            for dok in (target_dok, 2, 1, 3, 4):
                for qtype in ordered_types:
                    question = self._questions.find_one_unused(
                        chapter_name=chapter,
                        sub_concept="",
                        dok_level=dok,
                        question_type=qtype,
                        excluded_ids=excluded_ids,
                        topic_id=topic_id,
                        exclude_sub_concepts=blocked_subs,
                    )
                    if question:
                        return question

        # Chapter-wide fallback (drop topic filter).
        if topic_id:
            for chapter in bank_chapters:
                for dok in (target_dok, 2, 1, 3, 4):
                    for qtype in ordered_types:
                        question = self._questions.find_one_unused(
                            chapter_name=chapter,
                            sub_concept="",
                            dok_level=dok,
                            question_type=qtype,
                            excluded_ids=excluded_ids,
                            topic_id="",
                            exclude_sub_concepts=blocked_subs,
                        )
                        if question:
                            return question
        return None

    def next_question(self, session_id: str) -> tuple[Question, Any]:
        from iae.adaptive.multivariate_policy import MultivariateDecision

        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session.status != SessionStatus.ACTIVE:
            raise NoQuestionAvailable(f"Session is {session.status.value}.")
        if session.questions_asked >= session.max_questions:
            session.status = SessionStatus.COMPLETED
            self._sessions.update(session)
            raise NoQuestionAvailable("Session already complete.")

        chapter_ids = session.scope_chapters or [session.scope_chapter]
        bank_chapters = bank_chapter_names(chapter_ids, grade=session.grade)
        types = session.allowed_question_types or list(QuestionType)
        session_used = list(session.used_question_ids)
        permanently_blocked = self._sessions.served_question_ids(session.user_id)

        recent_topics: list[str] = []
        for attempt in session.history[-5:]:
            crumb = (attempt.adaptive_decision or "").strip()
            if "topic=" in crumb:
                recent_topics.append(crumb.split("topic=", 1)[1].split()[0])

        hist_ok = [a.is_correct for a in session.history]
        hist_types = [a.question_type for a in session.history]
        last = session.history[-1] if session.history else None

        decision: MultivariateDecision = select_next_item(
            elo_rating=session.elo_rating,
            chapter_ids=chapter_ids,
            bkt_snapshot=session.bkt_snapshot if isinstance(session.bkt_snapshot, dict) else None,
            allowed_question_types=types,
            previous_type=last.question_type if last else None,
            last_item_dok=last.dok_level if last else None,
            previous_correct=last.is_correct if last else None,
            previous_response_time_s=last.time_taken_seconds if last else None,
            recently_used_topics=recent_topics,
            history_correct=hist_ok,
            history_types=hist_types,
        )

        # Never repeat question_id in this session (hard). Soft prefer different
        # sub_concept than the last 1–2 attempts; if that fails, fall back immediately.
        recent_subs = [
            a.sub_concept
            for a in session.history[-2:]
            if a.sub_concept and str(a.sub_concept).strip()
        ]
        excluded = list(dict.fromkeys(session_used + permanently_blocked))

        question = None
        if recent_subs:
            question = self._find_question(
                bank_chapters=bank_chapters,
                types=types,
                target_dok=decision.dok_level,
                excluded_ids=excluded,
                topic_id=decision.topic_id,
                preferred_type=decision.question_type,
                exclude_sub_concepts=list(dict.fromkeys(recent_subs)),
            )

        # Graceful fallback: ignore sub_concept variety; still honor used_question_ids.
        if question is None:
            question = self._find_question(
                bank_chapters=bank_chapters,
                types=types,
                target_dok=decision.dok_level,
                excluded_ids=excluded,
                topic_id=decision.topic_id,
                preferred_type=decision.question_type,
                exclude_sub_concepts=None,
            )

        if question is None:
            question = self._find_question(
                bank_chapters=bank_chapters,
                types=types,
                target_dok=decision.dok_level,
                excluded_ids=session_used,
                topic_id=decision.topic_id,
                preferred_type=decision.question_type,
            )

        if question is None:
            question = self._find_question(
                bank_chapters=bank_chapters,
                types=types,
                target_dok=decision.dok_level,
                excluded_ids=[],
                topic_id="",
                preferred_type=decision.question_type,
            )

        if question is None:
            raise NoQuestionAvailable("No eligible approved questions left.")

        session.used_question_ids.append(question.id)
        session.questions_asked += 1
        # Stash last routing decision beside BKT session memory (not sent to C4).
        snapshot = dict(session.bkt_snapshot or {})
        snapshot["_last_routing"] = {
            "topic_id": decision.topic_id,
            "dok_level": decision.dok_level,
            "question_type": decision.question_type.value,
            "reason": decision.reason,
            "served_topic_id": question.topic_id,
        }
        session.bkt_snapshot = snapshot
        self._sessions.update(session)
        return question, decision

    def submit_answer(
        self,
        *,
        session_id: str,
        question_id: str,
        student_answer: str,
        time_taken_seconds: float,
    ) -> tuple:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session.status != SessionStatus.ACTIVE:
            raise RuntimeError(f"Session is {session.status.value}.")
        question = self._questions.get(question_id)
        if question is None:
            raise KeyError(question_id)

        result = self._grading.grade(question, student_answer)
        elo = update_elo(
            rating=session.elo_rating,
            item_dok=question.dok_level,
            is_correct=result.is_correct,
            response_time_s=time_taken_seconds,
            target_time_s=get_config().response_time_target_seconds,
            previous_type=question.question_type,
        )
        session.elo_rating = elo.new_rating

        attempt = AttemptRecord(
            question_id=question.id,
            question_type=question.question_type,
            chapter_name=question.chapter_name,
            sub_concept=question.sub_concept,
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
                f"topic={question.topic_id} elo={elo.new_rating:.1f} next_dok={elo.next_dok}"
            ),
            time_taken_seconds=time_taken_seconds,
        )
        session.history.append(attempt)

        chapter_ids = list(session.scope_chapters or ([session.scope_chapter] if session.scope_chapter else []))
        payload = build_analytics_payload(
            user_id=session.user_id,
            question=question,
            grade=result,
            student_answer=student_answer,
            response_time_s=time_taken_seconds,
            embedder=self._embedder,
            llm=self._analytics_llm,
            chapter_ids=chapter_ids or None,
        )
        if self._analytics is not None:
            try:
                self._analytics.insert(payload, session_id=session.session_id)
            except Exception:
                pass
        c4_response = self._c4.submit_assessment(payload)

        if isinstance(c4_response, dict) and c4_response.get("topic_bkt"):
            snapshot = dict(session.bkt_snapshot or {})
            snapshot["topic_bkt"] = c4_response["topic_bkt"]
            for key in ("chapter_ids", "topic_ids", "topics_by_chapter", "unknown_chapter_ids"):
                if key in c4_response:
                    snapshot[key] = c4_response[key]
            session.bkt_snapshot = snapshot

        similarity = payload.get("similarity_score")
        similarity_f = float(similarity) if similarity is not None else None
        # Permanently block only on correct or high-similarity pass.
        if result.is_correct or (similarity_f is not None and similarity_f >= _PASS_THRESHOLD):
            self._sessions.mark_served(
                user_id=session.user_id,
                question_id=question.id,
                session_id=session.session_id,
                topic_id=question.topic_id,
            )

        self._sessions.record_attempt(
            attempt,
            user_id=session.user_id,
            session_id=session.session_id,
            topic_id=question.topic_id,
            similarity_score=similarity_f,
            distractor_tag=payload.get("distractor_tag"),
            distractor_label=payload.get("distractor_label"),
        )
        if session.questions_asked >= session.max_questions:
            session.status = SessionStatus.COMPLETED
        self._sessions.update(session)
        return result, session, elo

    def get(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)
