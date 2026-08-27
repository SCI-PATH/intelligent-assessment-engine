"""Pre-generate the chapter-level question bank into PostgreSQL.

For every (Topic ID × DOK × Question Type), aim for 3 conceptually distinct
items (accept 1–2 if further attempts are paraphrases). Items are stored as
``approved`` so the student demo can serve them. Teacher-triggered generation
uses the same helpers and stores ``pending``.
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
    generate_distinct_for_combo,
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
        help="Override questions_per_combo from app.yaml (aim for 3 distinct).",
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

    llm = build_json_llm(timeout_s=config.groq_timeout_s)
    embedder = HuggingFaceEmbedder(config.embedding_model)
    per_combo = args.per_combo or config.questions_per_combo
    jaccard_max = config.distinctness_jaccard_max
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
    skipped_clones = 0
    pending: list[Question] = []
    print(
        f"Generating grade {args.grade}: {len(chapters)} chapters, "
        f"aim {per_combo} distinct per (topic × dok × type). "
        f"Groq fallbacks={config.groq_fallbacks}"
    )

    try:
        for chapter in chapters:
            topic_ids = [t for t in topics_for_bank_chapter(chapter, args.grade, args.topic_id) if t]
            if not topic_ids:
                print(f"  skip {chapter}: no Topic IDs in catalog")
                continue
            print(f"\n[{chapter}] topics={len(topic_ids)}")

            for topic_id in topic_ids:
                topic = get_topic(topic_id)
                skill = topic.skill if topic else ""
                chunks = retrieve_chunks(
                    store=store,
                    embedder=embedder,
                    grade=args.grade,
                    chapter=chapter,
                    topic_ids=[topic_id],
                    top_k=config.retrieval_top_k,
                )
                if not chunks:
                    print(f"  skip {topic_id}: no Chroma chunks")
                    continue

                context = format_context(c.text for c in chunks)
                chunk_ids = [c.id for c in chunks]
                chapter_scope = skill or "ChapterWide"
                print(f"  topic={topic_id} chunks={len(chunks)}")

                for dok in (1, 2, 3, 4):
                    for qtype in QuestionType:
                        print(
                            f"    generating dok={dok} type={qtype.value} "
                            f"(target {per_combo} distinct) ...",
                            flush=True,
                        )
                        before = len(pending) + succeeded
                        produced = generate_distinct_for_combo(
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
                            target_count=per_combo,
                            jaccard_max=jaccard_max,
                            status=QuestionStatus.APPROVED,
                            origin=QuestionOrigin.AI,
                            stop_on_rate_limit=args.stop_on_rate_limit,
                        )
                        if not produced:
                            failed += 1
                            print("      failed (0 distinct)")
                            continue
                        if len(produced) < per_combo:
                            skipped_clones += per_combo - len(produced)
                        pending.extend(produced)
                        succeeded += len(produced)
                        print(
                            f"      ok n={len(produced)} distinct "
                            f"(total {succeeded})"
                        )
                        if len(pending) >= 25:
                            questions_repo.insert_many(pending)
                            pending.clear()
                            print("  flushed batch to DB")
                        _ = before  # silence unused if refactor
    except RateLimitExceeded as exc:
        print(f"\nStopped early due to provider limit: {exc}")
    except KeyboardInterrupt:
        print(f"\nInterrupted. Flushing {len(pending)} buffered questions...")

    if pending:
        questions_repo.insert_many(pending)

    print(
        f"\nDone. Inserted {succeeded} questions, {failed} empty combos, "
        f"~{skipped_clones} clone slots left unfilled (by design)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
