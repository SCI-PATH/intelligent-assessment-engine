"""Teacher question-bank use cases (generate / review / author)."""

from __future__ import annotations

from dataclasses import dataclass

from iae.application.question_generation import generate_for_topic
from iae.core.models import (
    Question,
    QuestionOrigin,
    QuestionPayload,
    QuestionStatus,
    QuestionType,
)
from iae.core.protocols import IEmbedder, ILlmJson, IQuestionRepository, IVectorStore
from iae.core.skills import TopicRecord, get_topic, topics_for_grade


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
        limit: int = 100,
    ) -> list[Question]:
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
