"""Local persistent Chroma adapter implementing ``IVectorStore``."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import chromadb
from chromadb.config import Settings as ChromaSettings

from iae.core.models import Chunk
from iae.core.settings import get_settings

COLLECTION_NAME = "curriculum_chunks"


def _where(
    *,
    grade: int | None = None,
    chapter_name: str | None = None,
    topic_id: str | None = None,
) -> dict | None:
    clauses: list[dict] = []
    if grade is not None:
        clauses.append({"grade": grade})
    if chapter_name is not None:
        clauses.append({"chapter_name": chapter_name})
    if topic_id is not None:
        clauses.append({"topic_id": topic_id})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _chunk_from_chroma(doc: str, metadata: dict) -> Chunk:
    return Chunk(
        id=str(metadata.get("chunk_id") or ""),
        text=doc,
        chapter_name=str(metadata.get("chapter_name") or ""),
        sub_concept=str(metadata.get("sub_concept") or ""),
        page_start=int(metadata.get("page_start") or 0),
        page_end=int(metadata.get("page_end") or 0),
        source=str(metadata.get("source") or ""),
        grade=int(metadata.get("grade") or 6),
        topic_id=str(metadata.get("topic_id") or ""),
        skill=str(metadata.get("skill") or ""),
    )


class ChromaChunkStore:
    def __init__(self, persist_dir: str | Path | None = None) -> None:
        path = Path(persist_dir or get_settings().chroma_persist_dir)
        path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def replace_grade(
        self,
        grade: int,
        chunks: Iterable[Chunk],
        embeddings: list[list[float]],
    ) -> int:
        chunk_list = list(chunks)
        if len(chunk_list) != len(embeddings):
            raise ValueError("chunks and embeddings must be the same length")
        self.delete_by_grade(grade)
        return self.add_chunks(chunk_list, embeddings)

    def add_chunks(self, chunks: Iterable[Chunk], embeddings: list[list[float]]) -> int:
        chunk_list = list(chunks)
        if len(chunk_list) != len(embeddings):
            raise ValueError("chunks and embeddings must be the same length")
        if not chunk_list:
            return 0
        self._collection.add(
            ids=[chunk.id for chunk in chunk_list],
            documents=[chunk.text for chunk in chunk_list],
            embeddings=embeddings,
            metadatas=[self._metadata(chunk) for chunk in chunk_list],
        )
        return len(chunk_list)

    def delete_by_sources(self, grade: int, sources: Iterable[str]) -> int:
        wanted = {str(source) for source in sources}
        if not wanted:
            return 0
        existing = self._collection.get(where={"grade": grade}, include=["metadatas"])
        ids = [
            chunk_id
            for chunk_id, meta in zip(existing.get("ids") or [], existing.get("metadatas") or [])
            if str((meta or {}).get("source") or "") in wanted
        ]
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def delete_by_grade(self, grade: int) -> int:
        existing = self._collection.get(where={"grade": grade}, include=[])
        ids = existing.get("ids") or []
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def query(
        self,
        query_embedding: list[float],
        *,
        n_results: int,
        grade: int | None = None,
        chapter_name: str | None = None,
        topic_id: str | None = None,
    ) -> list[Chunk]:
        where = _where(grade=grade, chapter_name=chapter_name, topic_id=topic_id)
        filtered_count = self._filtered_count(where)
        if filtered_count == 0:
            return []
        kwargs: dict = {
            "query_embeddings": [query_embedding],
            "n_results": max(1, min(n_results, filtered_count)),
            "include": ["documents", "metadatas"],
        }
        if where is not None:
            kwargs["where"] = where
        result = self._collection.query(**kwargs)
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        chunks: list[Chunk] = []
        for doc, meta in zip(documents, metadatas):
            if doc is None or meta is None:
                continue
            chunks.append(_chunk_from_chroma(str(doc), dict(meta)))
        return chunks

    def find(
        self,
        *,
        grade: int | None = None,
        chapter_name: str | None = None,
        topic_id: str | None = None,
        limit: int | None = None,
    ) -> list[Chunk]:
        where = _where(grade=grade, chapter_name=chapter_name, topic_id=topic_id)
        kwargs: dict = {"include": ["documents", "metadatas"]}
        if where is not None:
            kwargs["where"] = where
        if limit is not None:
            kwargs["limit"] = limit
        result = self._collection.get(**kwargs)
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        chunks = [
            _chunk_from_chroma(str(doc), dict(meta or {}))
            for doc, meta in zip(documents, metadatas)
            if doc is not None
        ]
        if limit is not None:
            return chunks[:limit]
        return chunks

    def _filtered_count(self, where: dict | None) -> int:
        kwargs: dict = {"include": []}
        if where is not None:
            kwargs["where"] = where
        result = self._collection.get(**kwargs)
        return len(result.get("ids") or [])

    def count(self, *, grade: int | None = None) -> int:
        if grade is None:
            return int(self._collection.count())
        result = self._collection.get(where={"grade": grade}, include=[])
        return len(result.get("ids") or [])

    @staticmethod
    def _metadata(chunk: Chunk) -> dict:
        return {
            "chunk_id": chunk.id,
            "grade": int(chunk.grade),
            "chapter_name": chunk.chapter_name,
            "topic_id": chunk.topic_id or "",
            "skill": chunk.skill or "",
            "sub_concept": chunk.sub_concept or "",
            "page_start": int(chunk.page_start),
            "page_end": int(chunk.page_end),
            "source": chunk.source or "",
        }
