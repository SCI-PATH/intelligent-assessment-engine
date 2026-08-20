"""Teacher question-bank use cases (generate / review / author)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from iae.application.question_generation import generate_for_topic
from iae.core.models import (
    Question,
    QuestionOrigin,
    QuestionPayload,
    QuestionStatus,
    QuestionType,
    RejectionReason,
)
from iae.core.protocols import IEmbedder, ILlmJson, IQuestionRepository, IVectorStore
from iae.core.skills import TopicRecord, get_topic, topics_for_grade
from iae.infrastructure.postgres.amplitude_repo import PostgresAmplitudeRepository
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
                origin=QuestionOrigin.AI,
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
    ) -> list[Question]:
        resolved_grades = list(grades or [])
        if grade is not None and grade not in resolved_grades:
            resolved_grades.append(grade)
        if class_code and self.users is not None:
            for profile in self.users.list_users_by_class(class_code):
                if profile.role.value == "student" and profile.grade is not None:
                    if profile.grade not in resolved_grades:
                        resolved_grades.append(profile.grade)
        # Prefer multi-grade filter when available on the Postgres adapter.
        if isinstance(self.questions, PostgresQuestionRepository):
            return self.questions.list_questions(
                status=status,
                topic_id=topic_id,
                grade=None if resolved_grades else grade,
                grades=resolved_grades or None,
                dok_level=dok_level,
                question_type=question_type,
                limit=limit,
            )
        return self.questions.list_questions(
            status=status,
            topic_id=topic_id,
            grade=grade,
            limit=limit,
        )

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
