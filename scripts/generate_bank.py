"""Pre-generate the chapter-level question bank into PostgreSQL.

RAG context is retrieved from local Chroma (Topic ID metadata). Generated
items are stored as ``approved`` so the student demo can serve them.
Teacher-triggered generation uses the same helpers and stores ``pending``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from iae.application.question_generation import (
    RateLimitExceeded,
    curriculum_chapter_for_topic,
    format_context,
    generate_one,
    majority_topic,
    retrieve_chunks,
    topics_for_bank_chapter,
)
from iae.domain.curriculum import DEFAULT_GRADE, get_chapter_names
from iae.domain.models import Question, QuestionOrigin, QuestionStatus, QuestionType
from iae.config.settings import get_config, get_settings
from iae.domain.skills import get_topic
from iae.infrastructure.llm.factory import build_json_llm
from iae.infrastructure.postgres.engine import get_session_factory, init_schema
from iae.infrastructure.postgres.questions_repo import PostgresQuestionRepository
from iae.infrastructure.rag.chroma_store import ChromaChunkStore
from iae.infrastructure.rag.embeddings import HuggingFaceEmbedder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", action="append", help="Limit generation to a chapter (repeatable).")
    parser.add_argument("--grade", type=int, default=DEFAULT_GRADE, help="Curriculum grade to generate for (default: 6).")
    parser.add_argument("--topic-id", dest="topic_id", default=None, help="Retrieve RAG context for one canonical Topic ID.")
    parser.add_argument(
        "--per-combo",
        type=int,
        default=None,
        help="Override questions_per_combo from app.yaml (Rule of 3 default = 3).",
    )
    parser.add_argument("--stop-on-rate-limit", action="store_true", default=True, help="Stop immediately on provider 429/TPD limit.")
    args = parser.parse_args()

    settings = get_settings()
    config = get_config()
    init_schema()
    questions_repo = PostgresQuestionRepository(get_session_factory())
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
        chapters = [curriculum_chapter_for_topic(topic.chapter_title, args.grade)]
    if not chapters:
        print(
            f"Grade {args.grade} has no chapters in curriculum.yaml yet.",
            file=sys.stderr,
        )
        return 2

    succeeded = 0
    failed = 0
    pending: list[Question] = []

    try:
        for chapter in chapters:
            topic_ids = topics_for_bank_chapter(chapter, args.grade, args.topic_id)
            chunks = retrieve_chunks(
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

            context = format_context(c.text for c in chunks)
            chunk_ids = [c.id for c in chunks]
            topic_id, skill = majority_topic(chunks)
            if args.topic_id:
                topic = get_topic(args.topic_id)
                topic_id = args.topic_id
                skill = topic.skill if topic else skill
            chapter_scope = skill or "ChapterWide"

            for dok in (1, 2, 3, 4):
                for qtype in QuestionType:
                    for _ in range(per_combo):
                        question = generate_one(
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
                            status=QuestionStatus.APPROVED,
                            origin=QuestionOrigin.AI,
                            stop_on_rate_limit=args.stop_on_rate_limit,
                        )
                        if question is None:
                            failed += 1
                            continue
                        pending.append(question)
                        succeeded += 1
                        if len(pending) >= 25:
                            questions_repo.insert_many(pending)
                            pending.clear()
    except RateLimitExceeded as exc:
        print(f"\nStopped early due to provider limit: {exc}")

    if pending:
        questions_repo.insert_many(pending)

    print(f"\nDone. Inserted {succeeded} questions, {failed} failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
