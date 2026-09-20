"""Teacher question-bank use cases (generate / review / author)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from iae.application.question_generation import generate_for_topic
from iae.config.settings import get_config
from iae.domain.models import (
    MCQPayload,
    MultiBlankPayload,
    Question,
    QuestionOrigin,
    QuestionPayload,
    QuestionStatus,
    QuestionType,
    RejectionReason,
    ShortAnswerPayload,
    TrueFalsePayload,
)
from iae.domain.protocols import IEmbedder, ILlmJson, IQuestionRepository, IVectorStore
from iae.domain.skills import TopicRecord, get_topic, topics_for_grade
from iae.infrastructure.postgres.amplitude_repo import PostgresAmplitudeRepository
from iae.infrastructure.postgres.analytics_repo import PostgresAnalyticsRepository
from iae.infrastructure.postgres.questions_repo import PostgresQuestionRepository
from iae.prompts import render


class UnknownTopicError(KeyError):
    pass


class NoRagContextError(LookupError):
    pass


@dataclass
class TeacherService:
    questions: IQuestionRepository
    llm: ILlmJson
    store: IVectorStore
    embedder: IEmbedder
    retrieval_top_k: int
    generation_max_retries: int
    users: PostgresAmplitudeRepository | None = None
    analytics: PostgresAnalyticsRepository | None = None

    def list_topics(self, grade: int) -> list[TopicRecord]:
        return topics_for_grade(grade)

    def generate(
        self,
        *,
        topic_id: str,
        skill: str | None = None,
        dok_level: int = 2,
        question_type: QuestionType = QuestionType.MCQ,
        count: int = 1,
    ) -> list[Question]:
        if get_topic(topic_id) is None:
            raise UnknownTopicError(topic_id)
        try:
            created = generate_for_topic(
                llm=self.llm,
                store=self.store,
                embedder=self.embedder,
                topic_id=topic_id,
                skill=skill,
                dok_level=dok_level,
                question_type=question_type,
                count=count,
                top_k=self.retrieval_top_k,
                max_retries=self.generation_max_retries,
                status=QuestionStatus.PENDING,
                origin=QuestionOrigin.TEACHER,
                jaccard_max=get_config().distinctness_jaccard_max,
            )
        except LookupError as exc:
            raise NoRagContextError(str(exc)) from exc
        if created:
            self.questions.insert_many(created)
        return created

    def list_questions(
        self,
        *,
        status: QuestionStatus | None = None,
        topic_id: str | None = None,
        grade: int | None = None,
        grades: list[int] | None = None,
        dok_level: int | None = None,
        question_type: QuestionType | None = None,
        class_code: str | None = None,
        limit: int = 100,
        offset: int = 0,
        origin: QuestionOrigin | None = None,
        q: str | None = None,
        topic_id_prefix: str | None = None,
    ) -> tuple[list[Question], int]:
        # Class codes do not scope the shared bank — every student on the system
        # uses the same items. Keep the argument so older callers do not break.
        _ = class_code
        resolved_grades = list(grades or [])
        if grade is not None and grade not in resolved_grades:
            resolved_grades.append(grade)
        if isinstance(self.questions, PostgresQuestionRepository):
            return self.questions.list_page(
                status=status,
                topic_id=topic_id,
                grade=None if resolved_grades else grade,
                grades=resolved_grades or None,
                dok_level=dok_level,
                question_type=question_type,
                limit=limit,
                offset=offset,
                origin=origin,
                q=q,
                topic_id_prefix=topic_id_prefix,
            )
        items = self.questions.list_questions(
            status=status,
            topic_id=topic_id,
            grade=grade,
            limit=limit,
        )
        return items, len(items)

    def set_status(self, question_id: str, status: QuestionStatus) -> Question:
        updated = self.questions.set_status(question_id, status)
        if updated is None:
            raise KeyError(question_id)
        return updated

    def reject(
        self,
        question_id: str,
        *,
        reason: RejectionReason,
        notes: str | None = None,
    ) -> Question:
        if not isinstance(self.questions, PostgresQuestionRepository):
            return self.set_status(question_id, QuestionStatus.REJECTED)

        confirmed_ai = False
        explanation = notes
        if reason == RejectionReason.FACTUAL_ERROR:
            question = self.questions.get(question_id)
            if question is None:
                raise KeyError(question_id)
            prompt = render(
                "analytics/factual_error_check.jinja",
                question_type=question.question_type.value,
                chapter_name=question.chapter_name,
                topic_id=question.topic_id,
                payload_json=json.dumps(question.payload.model_dump(mode="json"), indent=2),
            )
            try:
                verdict = self.llm.generate_json(prompt, temperature=0.1)
                confirmed_ai = bool(verdict.get("is_factual_error"))
                ai_note = str(verdict.get("explanation") or "").strip()
                if ai_note:
                    explanation = f"{notes or ''}\nAI: {ai_note}".strip()
            except Exception:
                confirmed_ai = False

        updated = self.questions.reject(
            question_id,
            reason=reason,
            notes=explanation,
            confirmed_ai=confirmed_ai,
        )
        if updated is None:
            raise KeyError(question_id)
        return updated

    def add_custom(
        self,
        *,
        grade: int,
        chapter_name: str,
        topic_id: str,
        skill: str,
        dok_level: int,
        question_type: QuestionType,
        payload: QuestionPayload,
        sub_concept: str = "",
    ) -> Question:
        topic = get_topic(topic_id)
        if topic is None:
            raise UnknownTopicError(topic_id)
        if payload.type != question_type:
            raise ValueError("payload.type must match question_type")
        question = Question(
            chapter_name=chapter_name or topic.chapter_title,
            sub_concept=sub_concept or skill or topic.skill,
            dok_level=dok_level,
            question_type=question_type,
            payload=payload,
            grade=grade or topic.grade,
            topic_id=topic_id,
            skill=skill or topic.skill,
            status=QuestionStatus.APPROVED,
            origin=QuestionOrigin.TEACHER,
        )
        self.questions.insert_many([question])
        return question

    def most_missed_questions(
        self,
        *,
        grade: int | None = None,
        class_code: str | None = None,
        limit: int = 8,
    ) -> list[dict]:
        """Aggregate analytics_events by question; join bank rows for the stem.

        Ranked across every student on the system. ``class_code`` is ignored.
        """
        _ = class_code
        if self.analytics is None:
            return []
        rows = self.analytics.most_missed(
            user_ids=None,
            limit=max(limit * 4, 40),
        )
        out: list[dict] = []
        for question_id, attempt_count, incorrect_count in rows:
            question = self.questions.get(question_id)
            if question is None:
                continue
            if grade is not None and question.grade != grade:
                continue
            stem, correct, options = _stem_and_correct(question)
            most_selected, common_wrong = self._answer_insight(question)
            out.append(
                {
                    "question_id": question.id,
                    "prompt": stem or question_id,
                    "topic_id": question.topic_id,
                    "chapter_name": question.chapter_name,
                    "grade": question.grade,
                    "status": question.status.value,
                    "question_type": question.question_type.value,
                    "options": options,
                    "correct_answer": correct,
                    "most_selected": most_selected,
                    "common_wrong": common_wrong,
                    "incorrect_count": incorrect_count,
                    "attempt_count": attempt_count,
                    "miss_rate": round(incorrect_count / attempt_count, 3)
                    if attempt_count
                    else 0.0,
                }
            )
            if len(out) >= limit:
                break
        return out

    def _answer_insight(self, question: Question) -> tuple[dict | None, list[dict]]:
        if self.analytics is None:
            return None, []
        rows = self.analytics.answer_counts(question.id)
        if not rows:
            return None, []
        merged: dict[str, tuple[int, int]] = {}
        for raw, total, incorrect in rows:
            label = _format_student_answer(raw, question) or raw
            prev_total, prev_incorrect = merged.get(label, (0, 0))
            merged[label] = (prev_total + total, prev_incorrect + incorrect)
        ranked = sorted(merged.items(), key=lambda item: item[1][0], reverse=True)
        top_label, (top_total, _top_wrong) = ranked[0]
        most_selected = {"answer": top_label, "count": top_total}
        wrong = [
            {"answer": label, "count": incorrect}
            for label, (_total, incorrect) in ranked
            if incorrect > 0
        ]
        wrong.sort(key=lambda item: item["count"], reverse=True)
        return most_selected, wrong[:3]


def _stem_and_correct(question: Question) -> tuple[str, str, dict[str, str]]:
    payload = question.payload
    if isinstance(payload, MCQPayload):
        options = {str(k): str(v) for k, v in payload.options.items()}
        letter = (payload.correct_answer or "").strip().upper()
        text = options.get(letter, "")
        correct = f"{letter}. {text}".strip() if text else letter
        return payload.question.strip(), correct, options
    if isinstance(payload, TrueFalsePayload):
        return payload.question.strip(), payload.correct_answer, {}
    if isinstance(payload, ShortAnswerPayload):
        return payload.question.strip(), payload.ideal_answer.strip(), {}
    if isinstance(payload, MultiBlankPayload):
        correct = " · ".join(str(a) for a in payload.answers)
        return payload.paragraph.strip(), correct, {}
    dumped = payload.model_dump(mode="json")
    stem = ""
    for key in ("question", "text", "prompt", "paragraph"):
        value = dumped.get(key)
        if isinstance(value, str) and value.strip():
            stem = value.strip()
            break
    return stem, "", {}


def _format_student_answer(raw: str, question: Question) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    payload = question.payload
    if isinstance(payload, MCQPayload):
        letter = text[:1].upper()
        if letter in payload.options and (len(text) <= 2 or text[1:2] in {".", ")", ":"}):
            return f"{letter}. {payload.options[letter]}"
        upper = text.upper()
        for key, label in payload.options.items():
            if text == label or upper == f"{key}. {label}".upper():
                return f"{key}. {label}"
        return text
    if isinstance(payload, TrueFalsePayload):
        lower = text.lower()
        if lower.startswith("t"):
            return "True"
        if lower.startswith("f"):
            return "False"
        return text
    return text
