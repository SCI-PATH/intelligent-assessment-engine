"""Pre-generate the chapter-level question bank into PostgreSQL.

For every (Topic ID × DOK × Question Type), aim for conceptually distinct items
using MiniLM cosine similarity against existing stems for that topic_id (plus
stems accepted in this run). Accept 1+ high-quality items when further attempts
are paraphrases. All items are stored as ``approved``.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from iae.application.question_generation import (
    RateLimitExceeded,
    chunk_window,
    curriculum_chapter_for_topic,
    format_context,
    generate_one,
    retrieve_topic_chunk_pool,
    stem_text,
    topics_for_bank_chapter,
)
from iae.config.settings import get_config, get_settings
from iae.domain.chapter_catalog import normalize_chapter_id
from iae.domain.curriculum import DEFAULT_GRADE, get_chapter_names
from iae.domain.models import Question, QuestionOrigin, QuestionStatus, QuestionType
from iae.domain.protocols import IEmbedder
from iae.domain.skills import get_topic
from iae.infrastructure.llm.factory import build_json_llm, llm_provider_label
from iae.infrastructure.postgres.engine import get_session_factory, init_schema
from iae.infrastructure.postgres.questions_repo import PostgresQuestionRepository
from iae.infrastructure.rag.chroma_store import ChromaChunkStore
from iae.infrastructure.rag.embeddings import HuggingFaceEmbedder

# Cosine similarity at or above this vs any prior stem → reject as paraphrase.
COSINE_CLONE_MAX = 0.82


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _max_cosine_to_priors(
    candidate: str,
    prior_stems: list[str],
    prior_vectors: list[list[float]],
    embedder: IEmbedder,
) -> float:
    """Return max cosine of candidate vs prior stems (embed candidate once)."""
    text = (candidate or "").strip()
    if not text or not prior_stems:
        return 0.0
    cand_vec = embedder.embed([text])[0]
    best = 0.0
    for vec in prior_vectors:
        best = max(best, _cosine(cand_vec, vec))
    return best


def _load_topic_stems(
    questions_repo: PostgresQuestionRepository,
    *,
    topic_id: str,
    limit: int = 500,
) -> list[str]:
    existing = questions_repo.list_questions(topic_id=topic_id, limit=limit)
    stems: list[str] = []
    for q in existing:
        text = stem_text(q)
        if text:
            stems.append(text)
    return stems


def _resolve_chapter_id(chapter: str, grade: int, topic_id: str) -> str:
    """Canonical chapter_id for logging only (not stored on Question)."""
    from_topic = normalize_chapter_id(topic_id, grade=grade)
    if from_topic:
        return from_topic
    from_title = normalize_chapter_id(chapter, grade=grade)
    return from_title or ""


def _flush_pending(
    pending: list[Question],
    questions_repo: PostgresQuestionRepository,
    *,
    label: str = "batch",
) -> int:
    if not pending:
        return 0
    n = len(pending)
    questions_repo.insert_many(pending)
    pending.clear()
    print(f"  flushed {label} to DB ({n} questions)", flush=True)
    return n


def generate_distinct_with_embeddings(
    *,
    llm,
    embedder: IEmbedder,
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
    target_count: int,
    prior_stems: list[str],
    avoid_stems_max: int,
    stop_on_rate_limit: bool,
    cosine_max: float = COSINE_CLONE_MAX,
) -> tuple[list[Question], int]:
    """Aim for ``target_count`` embedding-distinct items; keep 1+ if clones only.

    Returns (accepted questions, rejected_clone_count).
    """
    target = max(1, int(target_count))
    extra = 3 if target >= 3 else 2
    attempts_budget = target + extra
    produced: list[Question] = []
    stems: list[str] = list(prior_stems)
    prior_vectors: list[list[float]] = []
    if stems:
        prior_vectors = embedder.embed(stems)
    rejected = 0

    for _ in range(attempts_budget):
        if len(produced) >= target:
            break
        # Cap stems sent to the LLM (cosine dedup still uses the full prior list).
        cap = max(0, int(avoid_stems_max))
        avoid = list(stems[-cap:]) if cap else []
        question = generate_one(
            llm=llm,
            chapter=chapter,
            sub_concept=sub_concept,
            dok=dok,
            qtype=qtype,
            context=context,
            chunk_ids=chunk_ids,
            grade=grade,
            topic_id=topic_id,
            skill=skill,
            max_retries=max_retries,
            status=QuestionStatus.APPROVED,
            origin=QuestionOrigin.AI,
            stop_on_rate_limit=stop_on_rate_limit,
            avoid_stems=avoid,
        )
        if question is None:
            continue
        text = stem_text(question)
        if not text:
            continue
        # Only compare against stems that existed before this candidate
        # (priors + already accepted). Empty priors → always accept first.
        compare_stems = stems
        compare_vecs = prior_vectors
        if compare_stems:
            sim = _max_cosine_to_priors(text, compare_stems, compare_vecs, embedder)
            if sim >= cosine_max:
                rejected += 1
                print(
                    f"      skip clone cosine={sim:.3f} "
                    f"(threshold {cosine_max}) dok={dok} type={qtype.value}",
                    flush=True,
                )
                continue
        produced.append(question)
        stems.append(text)
        prior_vectors.append(embedder.embed([text])[0])

    return produced, rejected


def _print_summary(
    *,
    attempted: int,
    inserted: int,
    failed_combos: int,
    combo_counts: Counter[tuple[str, int, str]],
    fallback_combos: list[str],
    zero_combos: list[str],
) -> None:
    print("\n" + "=" * 72)
    print("BANK GENERATION SUMMARY")
    print("=" * 72)
    print(f"  Combos attempted:     {attempted}")
    print(f"  Questions inserted:   {inserted}")
    print(f"  Empty combos (0):     {failed_combos}")
    print(f"  Fallback to 1 item:   {len(fallback_combos)}")
    print("-" * 72)
    print("  Per (topic_id × DOK × type):")
    if not combo_counts:
        print("    (none)")
    else:
        for (tid, dok, qtype), n in sorted(combo_counts.items()):
            print(f"    {tid} | DOK {dok} | {qtype}: {n}")
    if fallback_combos:
        print("-" * 72)
        print("  Combos that fell back to 1 item (conceptual duplication):")
        for line in fallback_combos:
            print(f"    {line}")
    if zero_combos:
        print("-" * 72)
        print("  Combos with 0 items (generation failed):")
        for line in zero_combos:
            print(f"    {line}")
    print("=" * 72)


def generate_for_grade(
    *,
    grade: int,
    chapters: list[str] | None,
    topic_id: str | None,
    per_combo: int,
    stop_on_rate_limit: bool,
    flush_batch_size: int,
    avoid_stems_max: int,
    questions_repo: PostgresQuestionRepository,
    store: ChromaChunkStore,
    llm,
    embedder: HuggingFaceEmbedder,
    config,
) -> tuple[int, int, Counter[tuple[str, int, str]], list[str], list[str]]:
    """Run bank generation for one grade. Returns summary counters."""
    if store.count(grade=grade) == 0:
        print(
            f"No Chroma chunks for grade {grade}. Run scripts/ingest_and_tag_chunks.py first.",
            file=sys.stderr,
        )
        return 0, 0, Counter(), [], [f"grade {grade}: no chroma"]

    chapter_list = list(chapters) if chapters else get_chapter_names(grade)
    if topic_id:
        topic = get_topic(topic_id)
        if topic is None:
            print(f"Unknown Topic ID: {topic_id}", file=sys.stderr)
            return 0, 0, Counter(), [], [f"unknown topic {topic_id}"]
        chapter_list = [curriculum_chapter_for_topic(topic.chapter_title, grade)]
    if not chapter_list:
        print(f"Grade {grade} has no chapters in curriculum.yaml yet.", file=sys.stderr)
        return 0, 0, Counter(), [], [f"grade {grade}: no chapters"]

    succeeded = 0
    failed = 0
    pending: list[Question] = []
    combo_counts: Counter[tuple[str, int, str]] = Counter()
    fallback_combos: list[str] = []
    zero_combos: list[str] = []
    attempted = 0

    print(
        f"\n>>> Generating grade {grade}: {len(chapter_list)} chapters, "
        f"aim {per_combo} distinct per (topic × dok × type), "
        f"cosine_clone_max={COSINE_CLONE_MAX}. "
        f"LLM={llm_provider_label()}"
    )

    try:
        for chapter in chapter_list:
            topic_ids = [t for t in topics_for_bank_chapter(chapter, grade, topic_id) if t]
            if not topic_ids:
                print(f"  skip {chapter}: no Topic IDs in catalog")
                continue
            print(f"\n[{chapter}] topics={len(topic_ids)}")

            for tid in topic_ids:
                topic = get_topic(tid)
                skill = topic.skill if topic else ""
                chapter_id = _resolve_chapter_id(chapter, grade, tid)
                ranked_pool, chunks_available, prompt_k = retrieve_topic_chunk_pool(
                    store=store,
                    embedder=embedder,
                    grade=grade,
                    chapter=chapter,
                    topic_id=tid,
                    max_k=config.retrieval_top_k,
                )
                if not ranked_pool:
                    print(f"  skip {tid}: no Chroma chunks")
                    continue

                chapter_scope = skill or "ChapterWide"
                db_stems = _load_topic_stems(questions_repo, topic_id=tid)
                # Stems accepted earlier in this run for the same topic (any DOK/type).
                run_topic_stems: list[str] = list(db_stems)
                print(
                    f"  topic={tid} chunks_stored={chunks_available} "
                    f"excerpts_per_prompt={prompt_k} prior_stems={len(db_stems)}"
                )

                combo_offset = 0
                for dok in (1, 2, 3, 4):
                    for qtype in QuestionType:
                        chunks = chunk_window(ranked_pool, prompt_k, combo_offset)
                        combo_offset += 1
                        context = format_context(c.text for c in chunks)
                        chunk_ids = [c.id for c in chunks]
                        attempted += 1
                        print(
                            f"    generating dok={dok} type={qtype.value} "
                            f"(target {per_combo} distinct, context_chunks={len(chunks)}) ...",
                            flush=True,
                        )
                        produced, rejected = generate_distinct_with_embeddings(
                            llm=llm,
                            embedder=embedder,
                            chapter=chapter,
                            sub_concept=chapter_scope,
                            dok=dok,
                            qtype=qtype,
                            context=context,
                            chunk_ids=chunk_ids,
                            grade=grade,
                            topic_id=tid,
                            skill=skill,
                            max_retries=config.generation_max_retries,
                            target_count=per_combo,
                            prior_stems=run_topic_stems,
                            avoid_stems_max=avoid_stems_max,
                            stop_on_rate_limit=stop_on_rate_limit,
                        )
                        combo_key = f"{tid} | DOK {dok} | {qtype.value}"
                        if not produced:
                            failed += 1
                            zero_combos.append(combo_key)
                            print("      failed (0 distinct)")
                            continue

                        if len(produced) == 1 and per_combo > 1:
                            fallback_combos.append(combo_key)
                        elif len(produced) < per_combo:
                            fallback_combos.append(
                                f"{combo_key} (n={len(produced)}, rejected_clones={rejected})"
                            )

                        for q in produced:
                            cid_log = chapter_id or "?"
                            print(
                                f"[Grade {grade} | Chapter {chapter} | "
                                f"chapter_id={cid_log} | Topic {tid} | "
                                f"DOK {dok} | Type {qtype.value}] "
                                f"-> Generated (approved)",
                                flush=True,
                            )
                            text = stem_text(q)
                            if text:
                                run_topic_stems.append(text)

                        pending.extend(produced)
                        succeeded += len(produced)
                        combo_counts[(tid, dok, qtype.value)] += len(produced)

                        if len(pending) >= flush_batch_size:
                            _flush_pending(pending, questions_repo)

                _flush_pending(pending, questions_repo, label=f"topic {tid} remainder")
    except RateLimitExceeded as exc:
        print(f"  provider limit during grade {grade}: {exc}", flush=True)
        raise
    finally:
        _flush_pending(pending, questions_repo, label="grade remainder")

    return attempted, succeeded, combo_counts, fallback_combos, zero_combos


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", action="append", help="Limit generation to a chapter (repeatable).")
    parser.add_argument(
        "--grade",
        type=int,
        default=None,
        help="Single curriculum grade (default: 6 unless --grades / --all-grades).",
    )
    parser.add_argument(
        "--grades",
        type=int,
        nargs="+",
        default=None,
        help="One or more grades to generate sequentially (e.g. --grades 6 7 8 9).",
    )
    parser.add_argument(
        "--all-grades",
        action="store_true",
        help="Generate for grades 6, 7, 8, and 9 in one run.",
    )
    parser.add_argument("--topic-id", dest="topic_id", default=None, help="Limit to one canonical Topic ID.")
    parser.add_argument(
        "--per-combo",
        type=int,
        default=None,
        help="Override questions_per_combo from app.yaml (default: 3 distinct per combo).",
    )
    parser.add_argument(
        "--stop-on-rate-limit",
        action="store_true",
        default=False,
        help="Stop immediately on provider 429/quota limit (default: retry).",
    )
    args = parser.parse_args()

    if args.all_grades:
        grades = [6, 7, 8, 9]
    elif args.grades:
        grades = list(args.grades)
    elif args.grade is not None:
        grades = [args.grade]
    else:
        grades = [DEFAULT_GRADE]

    settings = get_settings()
    config = get_config()
    init_schema()
    questions_repo = PostgresQuestionRepository(get_session_factory())
    store = ChromaChunkStore(settings.chroma_persist_dir)
    llm = build_json_llm()
    embedder = HuggingFaceEmbedder(config.embedding_model)
    per_combo = args.per_combo or config.questions_per_combo

    print(
        f"Bank generation LLM: {llm_provider_label()} "
        f"(switch via models.llm_provider in src/iae/config/app.yaml)"
    )

    total_attempted = 0
    total_inserted = 0
    all_combo_counts: Counter[tuple[str, int, str]] = Counter()
    all_fallback: list[str] = []
    all_zero: list[str] = []

    try:
        for grade in grades:
            attempted, inserted, counts, fallback, zero = generate_for_grade(
                grade=grade,
                chapters=args.chapter,
                topic_id=args.topic_id,
                per_combo=per_combo,
                stop_on_rate_limit=args.stop_on_rate_limit,
                flush_batch_size=config.flush_batch_size,
                avoid_stems_max=config.avoid_stems_max,
                questions_repo=questions_repo,
                store=store,
                llm=llm,
                embedder=embedder,
                config=config,
            )
            total_attempted += attempted
            total_inserted += inserted
            all_combo_counts.update(counts)
            all_fallback.extend(fallback)
            all_zero.extend(zero)
    except RateLimitExceeded as exc:
        print(f"\nStopped early due to provider limit: {exc}")
        print("(Partial progress was flushed to DB before exit.)")
    except KeyboardInterrupt:
        print("\nInterrupted.")
        print("(Partial progress was flushed to DB if a grade loop had started.)")

    _print_summary(
        attempted=total_attempted,
        inserted=total_inserted,
        failed_combos=len(all_zero),
        combo_counts=all_combo_counts,
        fallback_combos=all_fallback,
        zero_combos=all_zero,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
