"""``IQuestionRepository`` backed by MongoDB."""

from __future__ import annotations

import json
import time
from typing import Iterable
from pathlib import Path

from pymongo.database import Database

from iae.core.models import Question, QuestionType

_COLLECTION = "questions"
_DEBUG_LOG_PATH = Path("debug-b15ee2.log")


def _debug_log(*, run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "sessionId": "b15ee2",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass


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
            # Randomize candidate selection to avoid deterministic "first doc"
            # bias (e.g., repeatedly surfacing the same MCQ key pattern).
            sample = list(
                self._db[_COLLECTION].aggregate(
                    [
                        {"$match": query},
                        {"$sample": {"size": 1}},
                    ]
                )
            )
            doc = sample[0] if sample else None
            # #region agent log
            _debug_log(
                run_id="pre-fix",
                hypothesis_id="H4",
                location="src/iae/infrastructure/mongo/questions_repo.py:find_one_unused",
                message="Repository relaxation sample result",
                data={
                    "query_keys": sorted(list(query.keys())),
                    "matched": doc is not None,
                    "matched_question_type": (doc or {}).get("question_type"),
                    "matched_dok": (doc or {}).get("dok_level"),
                    "matched_chapter": (doc or {}).get("chapter_name"),
                    "matched_correct_answer": ((doc or {}).get("payload") or {}).get("correct_answer"),
                },
            )
            # #endregion
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
