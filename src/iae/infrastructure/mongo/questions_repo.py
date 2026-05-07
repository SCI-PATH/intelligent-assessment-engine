"""``IQuestionRepository`` backed by MongoDB."""

from __future__ import annotations

from typing import Iterable

from pymongo.database import Database

from iae.core.models import Question, QuestionType

_COLLECTION = "questions"


class MongoQuestionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def insert_many(self, questions: Iterable[Question]) -> int:
        docs = [q.model_dump(by_alias=True) for q in questions]
        if not docs:
            return 0
        result = self._db[_COLLECTION].insert_many(docs)
        return len(result.inserted_ids)

    def find_one_unused(
        self,
        *,
        chapter_name: str,
        sub_concept: str,
        dok_level: int,
        question_type: QuestionType,
        excluded_ids: list[str],
    ) -> Question | None:
        """Strict match first, then progressively relax filters.

        Each fallback is documented inline so the policy / API behaviour is
        traceable from a single place.
        """
        relaxations: list[dict] = [
            {  # exact match
                "chapter_name": chapter_name,
                "sub_concept": sub_concept,
                "dok_level": dok_level,
                "question_type": question_type.value,
            },
            {  # any question type for this sub-concept + dok
                "chapter_name": chapter_name,
                "sub_concept": sub_concept,
                "dok_level": dok_level,
            },
            {  # any sub-concept in chapter at this dok
                "chapter_name": chapter_name,
                "dok_level": dok_level,
            },
            {  # any dok in chapter
                "chapter_name": chapter_name,
            },
        ]
        for query in relaxations:
            if excluded_ids:
                query = {**query, "_id": {"$nin": excluded_ids}}
            doc = self._db[_COLLECTION].find_one(query)
            if doc:
                return Question(**doc)
        return None

    def count_matching(
        self,
        *,
        chapter_name: str | None = None,
        sub_concept: str | None = None,
        dok_level: int | None = None,
        question_type: QuestionType | None = None,
    ) -> int:
        query: dict = {}
        if chapter_name is not None:
            query["chapter_name"] = chapter_name
        if sub_concept is not None:
            query["sub_concept"] = sub_concept
        if dok_level is not None:
            query["dok_level"] = dok_level
        if question_type is not None:
            query["question_type"] = question_type.value
        return self._db[_COLLECTION].count_documents(query)

    def get(self, question_id: str) -> Question | None:
        doc = self._db[_COLLECTION].find_one({"_id": question_id})
        return Question(**doc) if doc else None
