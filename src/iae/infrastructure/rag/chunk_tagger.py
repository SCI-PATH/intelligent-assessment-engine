"""Assign each chunk a Sub_Concept by cosine similarity to concept descriptions.

Tagging happens *after* chapter assignment so we only ever compare a chunk
against the sub-concepts that belong to its chapter. This keeps the cost
linear in (chunks * concepts_per_chapter) rather than (chunks * total).
"""

from __future__ import annotations

import math
from collections import defaultdict

from iae.domain.curriculum import DEFAULT_GRADE, subconcepts_for_chapter
from iae.domain.models import Chunk, SubConcept
from iae.domain.protocols import IEmbedder


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def assign_subconcepts(chunks: list[Chunk], embedder: IEmbedder) -> list[Chunk]:
    """Mutate-and-return: each chunk gets its best matching ``sub_concept``.

    Chunks belonging to a chapter without any defined sub-concepts are tagged
    ``UNKNOWN`` so they remain queryable but never get picked for generation.
    """
    by_chapter: dict[tuple[int, str], list[int]] = defaultdict(list)
    for idx, chunk in enumerate(chunks):
        by_chapter[(chunk.grade or DEFAULT_GRADE, chunk.chapter_name)].append(idx)

    for (grade, chapter), indices in by_chapter.items():
        concepts = subconcepts_for_chapter(chapter, grade=grade)
        if not concepts:
            for i in indices:
                chunks[i].sub_concept = "UNKNOWN"
            continue

        concept_texts = [_describe(c) for c in concepts]
        concept_embeddings = embedder.embed(concept_texts)
        chunk_embeddings = embedder.embed([chunks[i].text for i in indices])

        for local_pos, chunk_idx in enumerate(indices):
            chunk_vec = chunk_embeddings[local_pos]
            best_concept = max(
                zip(concepts, concept_embeddings),
                key=lambda pair: _cosine(chunk_vec, pair[1]),
            )[0]
            chunks[chunk_idx].sub_concept = best_concept.name

    return chunks


def _describe(concept: SubConcept) -> str:
    return f"{concept.name}. {concept.description}"
