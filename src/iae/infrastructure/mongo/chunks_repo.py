"""``IChunkRepository`` backed by MongoDB."""

from __future__ import annotations

from typing import Iterable

from pymongo.database import Database

from iae.core.models import Chunk

_COLLECTION = "chunks"


class MongoChunkRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def replace_all(self, chunks: Iterable[Chunk]) -> int:
        coll = self._db[_COLLECTION]
        coll.delete_many({})
        docs = [c.model_dump() for c in chunks]
        if not docs:
            return 0
        result = coll.insert_many(docs)
        return len(result.inserted_ids)

    def find(
        self,
        *,
        chapter_name: str | None = None,
        sub_concept: str | None = None,
        limit: int | None = None,
    ) -> list[Chunk]:
        query: dict = {}
        if chapter_name is not None:
            query["chapter_name"] = chapter_name
        if sub_concept is not None:
            query["sub_concept"] = sub_concept
        cursor = self._db[_COLLECTION].find(query)
        if limit is not None:
            cursor = cursor.limit(limit)
        return [Chunk(**doc) for doc in cursor]

    def count(self) -> int:
        return self._db[_COLLECTION].count_documents({})
