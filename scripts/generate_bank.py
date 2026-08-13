"""Pre-generate the chapter-level question bank.

RAG context is retrieved from local Chroma (Topic ID metadata). Parsed
questions are still written to Mongo until the Phase 3 Postgres cutover.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from pydantic import ValidationError

from iae.core.curriculum import DEFAULT_GRADE, get_chapter_names
from iae.core.models import (
    Chunk,
    MCQPayload,
    MultiBlankPayload,
    Question,
    QuestionType,
    ShortAnswerPayload,
    TrueFalsePayload,
)
from iae.core.settings import get_config, get_settings
from iae.core.skills import get_topic, normalize_chapter_name, topics_for_chapter
from iae.infrastructure.llm.factory import build_json_llm
from iae.infrastructure.mongo.client import ensure_indexes, get_database
from iae.infrastructure.mongo.questions_repo import MongoQuestionRepository
from iae.infrastructure.rag.chroma_store import ChromaChunkStore
from iae.infrastructure.rag.embeddings import HuggingFaceEmbedder
from iae.prompts import render

DOK_DESCRIPTORS: dict[int, str] = {
    1: "Recall: identify or state a single fact from the text.",
    2: "Skill / Concept: explain a process or compare two ideas using textbook content.",
    3: "Strategic Thinking: justify, infer, or apply concepts to a short scenario.",
    4: "Extended Thinking: synthesize across paragraphs or design a small investigation.",
}

PROMPT_FOR_TYPE: dict[QuestionType, str] = {
    QuestionType.MCQ: "question_bank_generation/mcq.jinja",
    QuestionType.SHORT_ANSWER: "question_bank_generation/short_answer.jinja",
    QuestionType.MULTI_BLANK: "question_bank_generation/multi_blank.jinja",
    QuestionType.TRUE_FALSE: "question_bank_generation/true_false.jinja",
}


class RateLimitExceeded(RuntimeError):
    """Raised when provider daily quota is exhausted."""


@dataclass
class GenerationStats:
    succeeded: int = 0
    failed: int = 0


_BLANK_TOKEN_RE = re.compile(r"\[_+\]|_{3,}|\[\s*blank\s*\d+\s*\]|\[\s*\]", re.IGNORECASE)


def _canonicalize_blanks(paragraph: str) -> str:
    return _BLANK_TOKEN_RE.sub("[_____]", paragraph)


def _shuffle_mcq_options(raw: dict) -> dict:
    options = raw.get("options", {})
    correct_letter = str(raw.get("correct_answer", "")).strip().upper()
    if not isinstance(options, dict) or len(options) != 4 or correct_letter not in options:
        raise ValueError("Invalid MCQ payload shape")

    pairs = [(k, str(v).strip()) for k, v in options.items()]
    random.shuffle(pairs)
    letters = ("A", "B", "C", "D")

    new_options: dict[str, str] = {}
    new_correct = "A"
    for idx, (old_key, text) in enumerate(pairs):
        letter = letters[idx]
        new_options[letter] = text
        if old_key == correct_letter:
            new_correct = letter

    return {
        "question": str(raw.get("question", "")).strip(),
        "options": new_options,
        "correct_answer": new_correct,
    }


def _normalize_short_answer(raw: dict) -> dict:
    keywords = [str(k).strip().lower() for k in raw.get("keywords", []) if str(k).strip()]
    deduped: list[str] = []
    for kw in keywords:
        if kw not in deduped:
            deduped.append(kw)
    if len(deduped) < 3:
        raise ValueError("ShortAnswer requires at least 3 usable keywords")
    return {
        "question": str(raw.get("question", "")).strip(),
        "ideal_answer": str(raw.get("ideal_answer", "")).strip(),
        "keywords": deduped[:6],
    }


def _normalize_multiblank(raw: dict) -> dict:
    answers = [str(a).strip().lower() for a in raw.get("answers", []) if str(a).strip()]
    if not (3 <= len(answers) <= 5):
        raise ValueError("MultiBlank requires 3-5 non-empty answers")

    paragraph = _canonicalize_blanks(str(raw.get("paragraph", "")).strip())
    blanks = _BLANK_TOKEN_RE.findall(paragraph)
    if len(blanks) != len(answers):
        raise ValueError("MultiBlank paragraph blank count must match answers length")

    return {"paragraph": paragraph, "answers": answers}


def _normalize_true_false(raw: dict) -> dict:
    answer = str(raw.get("correct_answer", "")).strip().lower()
    if answer in ("t", "true"):
        canonical = "True"
    elif answer in ("f", "false"):
        canonical = "False"
    else:
        raise ValueError("TrueFalse correct_answer must be True/False")
    return {
        "question": str(raw.get("question", "")).strip(),
        "correct_answer": canonical,
    }


def _build_payload(qtype: QuestionType, raw: dict):
    if qtype == QuestionType.MCQ:
        return MCQPayload(**_shuffle_mcq_options(raw))
    if qtype == QuestionType.SHORT_ANSWER:
        return ShortAnswerPayload(**_normalize_short_answer(raw))
    if qtype == QuestionType.MULTI_BLANK:
        return MultiBlankPayload(**_normalize_multiblank(raw))
    return TrueFalsePayload(**_normalize_true_false(raw))


def _format_context(chunk_texts: Iterable[str]) -> str:
    return "\n\n---\n\n".join(t.strip() for t in chunk_texts)


def _majority_topic(chunks: list[Chunk]) -> tuple[str, str]:
    tagged = [(c.topic_id, c.skill) for c in chunks if c.topic_id]
    if not tagged:
        return "", ""
    topic_id = Counter(pair[0] for pair in tagged).most_common(1)[0][0]
    skill = next(skill for tid, skill in tagged if tid == topic_id)
    return topic_id, skill


def _retrieve_chunks(
    *,
    store: ChromaChunkStore,
    embedder: HuggingFaceEmbedder,
    grade: int,
    chapter: str,
    topic_ids: list[str | None],
    top_k: int,
) -> list[Chunk]:
    """Pull RAG context from Chroma, preferring Topic ID filters."""
    collected: list[Chunk] = []
    seen: set[str] = set()
    query_bits = [chapter]
    for topic_id in topic_ids:
        if topic_id:
            topic = get_topic(topic_id)
            if topic and topic.skill:
                query_bits.append(topic.skill)
    query_embedding = embedder.embed([" ".join(query_bits)])[0]

    for topic_id in topic_ids:
        hits = store.query(
            query_embedding,
            n_results=top_k,
            grade=grade,
            chapter_name=None if topic_id else chapter,
            topic_id=topic_id,
        )
        if not hits and topic_id:
            hits = store.find(grade=grade, topic_id=topic_id, limit=top_k)
        for chunk in hits:
            if chunk.id in seen:
                continue
            seen.add(chunk.id)
            collected.append(chunk)
            if len(collected) >= top_k:
                return collected

    if not collected:
        collected = store.find(grade=grade, chapter_name=chapter, limit=top_k)
    return collected[:top_k]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", action="append", help="Limit generation to a chapter (repeatable).")
    parser.add_argument("--grade", type=int, default=DEFAULT_GRADE, help="Curriculum grade to generate for (default: 6).")
    parser.add_argument("--topic-id", dest="topic_id", default=None, help="Retrieve RAG context for one canonical Topic ID.")
    parser.add_argument("--per-combo", type=int, default=None, help="Override questions_per_combo from app.yaml.")
    parser.add_argument("--stop-on-rate-limit", action="store_true", default=True, help="Stop immediately on provider 429/TPD limit.")
    args = parser.parse_args()

    settings = get_settings()
    config = get_config()
    db = get_database()
    ensure_indexes(db)
    questions_repo = MongoQuestionRepository(db)
    store = ChromaChunkStore(settings.chroma_persist_dir)
    if store.count(grade=args.grade) == 0:
        print(
            f"No Chroma chunks for grade {args.grade}. Run scripts/ingest_and_tag_chunks.py first.",
            file=sys.stderr,
        )
        return 1

    llm = build_json_llm(model=config.llm_model)
    embedder = HuggingFaceEmbedder(config.embedding_model)
    per_combo = args.per_combo or config.questions_per_combo
    chapters = args.chapter or get_chapter_names(args.grade)
    if args.topic_id:
        topic = get_topic(args.topic_id)
        if topic is None:
            print(f"Unknown Topic ID: {args.topic_id}", file=sys.stderr)
            return 2
        needle = normalize_chapter_name(topic.chapter_title)
        chapters = [topic.chapter_title]
        for name in get_chapter_names(args.grade):
            if normalize_chapter_name(name) == needle:
                chapters = [name]
                break
    if not chapters:
        print(
            f"Grade {args.grade} has no chapters in curriculum.yaml yet.",
            file=sys.stderr,
        )
        return 2

    stats = GenerationStats()
    pending: list[Question] = []

    try:
        for chapter in chapters:
            topic_ids = [args.topic_id] if args.topic_id else [t.topic_id for t in topics_for_chapter(chapter, args.grade)]
            if not topic_ids:
                topic_ids = [None]
            chunks = _retrieve_chunks(
                store=store,
                embedder=embedder,
                grade=args.grade,
                chapter=chapter,
                topic_ids=topic_ids,
                top_k=config.retrieval_top_k,
            )
            if not chunks:
                print(f"  skip {chapter}: no Chroma chunks")
                continue

            context = _format_context(c.text for c in chunks)
            chunk_ids = [c.id for c in chunks]
            topic_id, skill = _majority_topic(chunks)
            chapter_scope = skill or "ChapterWide"

            for dok in (1, 2, 3, 4):
                for qtype in QuestionType:
                    for _ in range(per_combo):
                        question = _generate_one(
                            llm=llm,
                            chapter=chapter,
                            sub_concept=chapter_scope,
                            dok=dok,
                            qtype=qtype,
                            context=context,
                            chunk_ids=chunk_ids,
                            grade=args.grade,
                            topic_id=topic_id,
                            skill=skill,
                            max_retries=config.generation_max_retries,
                            stop_on_rate_limit=args.stop_on_rate_limit,
                        )
                        if question is None:
                            stats.failed += 1
                            continue
                        pending.append(question)
                        stats.succeeded += 1

                        if len(pending) >= 25:
                            questions_repo.insert_many(pending)
                            pending.clear()
    except RateLimitExceeded as exc:
        print(f"\nStopped early due to provider limit: {exc}")

    if pending:
        questions_repo.insert_many(pending)

    print(f"\nDone. Inserted {stats.succeeded} questions, {stats.failed} failures.")
    return 0


def _generate_one(
    *,
    llm,
    chapter: str,
    sub_concept: str,
    dok: int,
    qtype: QuestionType,
    context: str,
    chunk_ids: list[str],
    grade: int,
    topic_id: str,
    skill: str,
    max_retries: int,
    stop_on_rate_limit: bool,
) -> Question | None:
    prompt = render(
        PROMPT_FOR_TYPE[qtype],
        chapter_name=chapter,
        sub_concept=sub_concept,
        dok_level=dok,
        dok_descriptor=DOK_DESCRIPTORS[dok],
        context=context,
    )
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            raw = llm.generate_json(prompt, temperature=0.7)
            payload = _build_payload(qtype, raw)
            return Question(
                chapter_name=chapter,
                sub_concept=sub_concept,
                dok_level=dok,
                question_type=qtype,
                payload=payload,
                chunk_ids=chunk_ids,
                grade=grade,
                topic_id=topic_id,
                skill=skill,
            )
        except (ValidationError, ValueError, KeyError) as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
        except Exception as exc:
            last_error = exc
            msg = str(exc).lower()
            if stop_on_rate_limit and ("rate limit" in msg or "429" in msg or "tpd" in msg):
                raise RateLimitExceeded(str(exc)) from exc
            time.sleep(1.0 * (attempt + 1))
    print(f"    ! {chapter} / DOK{dok} / {qtype.value} failed: {last_error}")
    return None


if __name__ == "__main__":
    raise SystemExit(main())



