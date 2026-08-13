"""Assign each chunk a canonical Topic ID from the Excel skill catalog."""

from __future__ import annotations

import math
from collections import defaultdict

from iae.core.curriculum import DEFAULT_GRADE
from iae.core.models import Chunk
from iae.core.protocols import IEmbedder
from iae.core.skills import TopicRecord, describe_topic, topics_for_chapter

# Below this cosine, fall back to the first topic of the chapter.
_WEAK_SIMILARITY = 0.30


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def assign_topic_ids(chunks: list[Chunk], embedder: IEmbedder) -> list[Chunk]:
    """Mutate-and-return: each chunk gets ``topic_id`` + ``skill``.

    Matching is scoped to (grade, chapter) so a Grade 6 magnets chunk cannot
    pick up a Grade 8 magnets topic. Weak matches fall back to the first
    catalog row for that chapter.
    """
    by_chapter: dict[tuple[int, str], list[int]] = defaultdict(list)
    for idx, chunk in enumerate(chunks):
        by_chapter[(chunk.grade or DEFAULT_GRADE, chunk.chapter_name)].append(idx)

    unmatched_chapters: list[str] = []
    for (grade, chapter), indices in by_chapter.items():
        topics = topics_for_chapter(chapter, grade=grade)
        if not topics:
            unmatched_chapters.append(f"G{grade} {chapter}")
            for i in indices:
                chunks[i].topic_id = ""
                chunks[i].skill = ""
            continue

        topic_embeddings = embedder.embed([describe_topic(t) for t in topics])
        chunk_embeddings = embedder.embed([chunks[i].text for i in indices])
        fallback = topics[0]

        for local_pos, chunk_idx in enumerate(indices):
            scores = [
                (_cosine(chunk_embeddings[local_pos], topic_vec), topic)
                for topic, topic_vec in zip(topics, topic_embeddings)
            ]
            best_score, best_topic = max(scores, key=lambda pair: pair[0])
            chosen: TopicRecord = best_topic if best_score >= _WEAK_SIMILARITY else fallback
            chunks[chunk_idx].topic_id = chosen.topic_id
            chunks[chunk_idx].skill = chosen.skill

    if unmatched_chapters:
        print(
            "No Excel Topic IDs for chapters: " + "; ".join(unmatched_chapters),
            flush=True,
        )
    return chunks
