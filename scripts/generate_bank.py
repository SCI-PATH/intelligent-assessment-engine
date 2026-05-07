"""Pre-generate the chapter-level question bank into MongoDB Atlas.

For each (chapter, DOK 1-4, question type) combination we render a
chapter-grounded prompt against cached chunks and persist parsed JSON as a
typed ``Question``.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Iterable

from pydantic import ValidationError

from iae.core.curriculum import get_chapter_names
from iae.core.models import (
    MCQPayload,
    MultiBlankPayload,
    Question,
    QuestionType,
    ShortAnswerPayload,
    TrueFalsePayload,
)
from iae.core.settings import get_config, get_settings
from iae.infrastructure.llm.factory import build_json_llm
from iae.infrastructure.mongo.chunks_repo import MongoChunkRepository
from iae.infrastructure.mongo.client import ensure_indexes, get_database
from iae.infrastructure.mongo.questions_repo import MongoQuestionRepository
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


def _build_payload(qtype: QuestionType, raw: dict):
    if qtype == QuestionType.MCQ:
        return MCQPayload(**raw)
    if qtype == QuestionType.SHORT_ANSWER:
        return ShortAnswerPayload(**raw)
    if qtype == QuestionType.MULTI_BLANK:
        return MultiBlankPayload(**raw)
    return TrueFalsePayload(**raw)


def _format_context(chunk_texts: Iterable[str]) -> str:
    return "\n\n---\n\n".join(t.strip() for t in chunk_texts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", action="append", help="Limit generation to a chapter (repeatable).")
    parser.add_argument("--per-combo", type=int, default=None, help="Override questions_per_combo from app.yaml.")
    parser.add_argument("--stop-on-rate-limit", action="store_true", default=True, help="Stop immediately on provider 429/TPD limit.")
    args = parser.parse_args()

    settings = get_settings()
    config = get_config()
    db = get_database()
    ensure_indexes(db)
    chunks_repo = MongoChunkRepository(db)
    questions_repo = MongoQuestionRepository(db)
    if chunks_repo.count() == 0:
        print("No chunks in Mongo. Run scripts/ingest_and_tag_chunks.py first.", file=sys.stderr)
        return 1

    llm = build_json_llm(model=config.llm_model)
    per_combo = args.per_combo or config.questions_per_combo
    chapters = args.chapter or get_chapter_names()

    stats = GenerationStats()
    pending: list[Question] = []

    try:
        for chapter in chapters:
            chunks = chunks_repo.find(chapter_name=chapter, limit=config.retrieval_top_k)
            if not chunks:
                print(f"  skip {chapter}: no chunks tagged")
                continue

            context = _format_context(c.text for c in chunks)
            chunk_ids = [c.id for c in chunks]
            chapter_scope = "ChapterWide"

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



