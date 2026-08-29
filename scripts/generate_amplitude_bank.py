"""Generate exactly 10 Aptitude placement questions per grade (MCQ / TrueFalse).

Uses Aptitude Baseline Ladder (ABL-1 Recall, ABL-2 Apply, ABL-3 Connect).
Writes only to ``question_engine.amplitude_questions`` (status=approved).
Does NOT touch the adaptive ``questions`` bank.

Design (why these 10, not any other 10)
---------------------------------------
Content: pick 10 chapters **evenly spaced** through the grade Table of
Contents (not “the first 10”). One canonical Topic ID per selected chapter
(the first listed skill = the chapter’s core idea). That yields a
deterministic, replicable form that samples the whole syllabus
(living systems / matter / energy / earth) instead of Term 1 only.

Difficulty vs chapter are **orthogonal**: the 10 selected chapters are
interleaved (front of the year mixed with later units) so ABL-1 is not
only early-book recall and ABL-3 is not only late-book content.

Difficulty: 4× ABL-1, 4× ABL-2, 2× ABL-3, shown easy→hard.
Format: 7 MCQ + 3 True/False (one TF at each ABL band).

Uniqueness: MiniLM cosine ≥ 0.82 vs stems already accepted this grade
→ reject as paraphrase and try another topic.

Usage
-----
    python -m scripts.generate_amplitude_bank --grade 6 --force
    python -m scripts.generate_amplitude_bank --all-grades --force
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from iae.application.question_generation import (
    RateLimitExceeded,
    build_payload,
    curriculum_chapter_for_topic,
    format_context,
    retrieve_topic_chunk_pool,
    stem_text,
)
from iae.config.settings import get_config, get_settings
from iae.domain.chapter_catalog import normalize_chapter_id
from iae.domain.curriculum import get_chapter_names
from iae.domain.models import Question, QuestionOrigin, QuestionStatus, QuestionType
from iae.domain.protocols import IEmbedder
from iae.domain.skills import get_topic, topics_for_grade
from iae.infrastructure.llm.factory import build_json_llm, llm_provider_label
from iae.infrastructure.postgres.amplitude_repo import PostgresAmplitudeRepository
from iae.infrastructure.postgres.engine import get_session_factory, init_schema
from iae.infrastructure.rag.chroma_store import ChromaChunkStore
from iae.infrastructure.rag.embeddings import HuggingFaceEmbedder
from iae.prompts import render

ABL_DESCRIPTORS: dict[int, str] = {
    1: "Recall — syllabus fact, definition, label, or simple recognition.",
    2: "Apply — use one familiar syllabus idea in a short classroom/everyday situation.",
    3: "Connect — link two grade-appropriate ideas or reject a common misconception.",
}

# Exactly 10 slots: easy→hard. 4 recall, 4 apply, 2 connect. One TF per ABL band.
SLOT_PLAN: list[tuple[int, int, QuestionType]] = [
    (1, 1, QuestionType.MCQ),
    (2, 1, QuestionType.MCQ),
    (3, 1, QuestionType.MCQ),
    (4, 1, QuestionType.TRUE_FALSE),
    (5, 2, QuestionType.MCQ),
    (6, 2, QuestionType.MCQ),
    (7, 2, QuestionType.MCQ),
    (8, 2, QuestionType.TRUE_FALSE),
    (9, 3, QuestionType.MCQ),
    (10, 3, QuestionType.TRUE_FALSE),
]

PROMPT_FOR_TYPE = {
    QuestionType.MCQ: "amplitude_generation/mcq.jinja",
    QuestionType.TRUE_FALSE: "amplitude_generation/true_false.jinja",
}

PLACEMENT_SIZE = 10
COSINE_CLONE_MAX = 0.82


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _max_cosine_to_priors(
    candidate: str,
    prior_vectors: list[list[float]],
    embedder: IEmbedder,
) -> float:
    text = (candidate or "").strip()
    if not text or not prior_vectors:
        return 0.0
    cand_vec = embedder.embed([text])[0]
    return max(_cosine(cand_vec, vec) for vec in prior_vectors)


def _evenly_spaced_indices(n: int, k: int) -> list[int]:
    """k unique indices spanning [0, n-1] in curriculum order."""
    if n <= 0:
        return []
    take = min(k, n)
    if take == 1:
        return [0]
    chosen: list[int] = []
    used: set[int] = set()
    for i in range(take):
        idx = round(i * (n - 1) / (take - 1))
        if idx in used:
            for delta in range(1, n):
                found = False
                for cand in (idx + delta, idx - delta):
                    if 0 <= cand < n and cand not in used:
                        idx = cand
                        found = True
                        break
                if found:
                    break
        used.add(idx)
        chosen.append(idx)
    return sorted(chosen)


def _interleave_halves(items: list) -> list:
    """Mix early-year chapters with later units so ABL is not confounded with ToC order."""
    if len(items) < 2:
        return list(items)
    mid = len(items) // 2
    front, back = items[:mid], items[mid:]
    out: list = []
    for a, b in zip(front, back):
        out.append(a)
        out.append(b)
    if len(front) > len(back):
        out.extend(front[len(back) :])
    elif len(back) > len(front):
        out.extend(back[len(front) :])
    return out


def _topics_by_chapter(grade: int) -> dict[str, list]:
    chapter_names = get_chapter_names(grade)
    buckets: dict[str, list] = {name: [] for name in chapter_names}
    for topic in topics_for_grade(grade):
        chapter = curriculum_chapter_for_topic(topic.chapter_title, grade)
        if chapter in buckets:
            buckets[chapter].append(topic)
        else:
            buckets.setdefault(chapter, []).append(topic)
    return buckets


def _as_candidate(topic, chapter: str) -> tuple[str, str, str]:
    return (topic.topic_id, chapter, topic.skill or "")


def _chapter_spread_candidates(grade: int) -> list[tuple[str, str, str]]:
    """Primary: 10 evenly spaced chapters (interleaved). Then unused chapters, then extra topics."""
    chapter_names = get_chapter_names(grade)
    buckets = _topics_by_chapter(grade)
    spaced = [chapter_names[i] for i in _evenly_spaced_indices(len(chapter_names), PLACEMENT_SIZE)]
    primary_chapters = _interleave_halves(spaced)

    assigned: list[tuple[str, str, str]] = []
    used_topics: set[str] = set()

    def take_first(chapter: str) -> None:
        items = buckets.get(chapter) or []
        if not items:
            return
        topic = items[0]
        if topic.topic_id in used_topics:
            return
        used_topics.add(topic.topic_id)
        assigned.append(_as_candidate(topic, chapter))

    for chapter in primary_chapters:
        take_first(chapter)
    for chapter in chapter_names:
        if chapter not in primary_chapters:
            take_first(chapter)
    for chapter in chapter_names:
        for topic in buckets.get(chapter) or []:
            if topic.topic_id not in used_topics:
                used_topics.add(topic.topic_id)
                assigned.append(_as_candidate(topic, chapter))
    return assigned


def _generate_slot(
    *,
    llm,
    store,
    embedder,
    grade: int,
    position: int,
    baseline_level: int,
    qtype: QuestionType,
    topic_id: str,
    chapter: str,
    skill: str,
    top_k: int,
    max_retries: int,
    avoid_stems: list[str],
) -> Question | None:
    topic = get_topic(topic_id)
    if topic is None:
        print(f"    skip {topic_id}: unknown topic", flush=True)
        return None
    ranked_pool, chunks_available, prompt_k = retrieve_topic_chunk_pool(
        store=store,
        embedder=embedder,
        grade=grade,
        chapter=chapter,
        topic_id=topic_id,
        max_k=top_k,
    )
    chunks = ranked_pool[:prompt_k]
    if not chunks:
        print(
            f"    skip {topic_id}: no Chroma chunks (ingest this grade first)",
            flush=True,
        )
        return None
    context = format_context(c.text for c in chunks)
    prompt = render(
        PROMPT_FOR_TYPE[qtype],
        grade=grade,
        chapter_name=chapter,
        topic_id=topic_id,
        skill=skill or topic.skill,
        baseline_level=baseline_level,
        abl_descriptor=ABL_DESCRIPTORS[baseline_level],
        context=context,
        avoid_stems=list(avoid_stems or []),
    )
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            raw = llm.generate_json(prompt, temperature=0.55)
            payload = build_payload(qtype, raw)
            return Question(
                chapter_name=chapter,
                sub_concept=skill or topic.skill or "Aptitude",
                dok_level=baseline_level,
                question_type=qtype,
                payload=payload,
                chunk_ids=[c.id for c in chunks],
                grade=grade,
                topic_id=topic_id,
                skill=skill or topic.skill or "",
                status=QuestionStatus.APPROVED,
                origin=QuestionOrigin.AMPLITUDE,
            )
        except (ValidationError, ValueError, KeyError) as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
        except Exception as exc:
            last_error = exc
            msg = str(exc).lower()
            if "rate limit" in msg or "429" in msg or "tpd" in msg:
                raise RateLimitExceeded(str(exc)) from exc
            time.sleep(1.0 * (attempt + 1))
    print(
        f"    skip {topic_id}: ABL-{baseline_level} {qtype.value} failed ({last_error})",
        flush=True,
    )
    return None


def generate_grade(*, grade: int, force: bool, repo: PostgresAmplitudeRepository) -> int:
    existing = repo.count_amplitude_questions(grade)
    if existing == 10 and not force:
        print(
            f"Grade {grade}: already has 10 Aptitude items — skip (use --force to regenerate).",
            flush=True,
        )
        return 0
    if existing and force:
        print(
            f"Grade {grade}: regenerating (--force); replacing {existing} items.",
            flush=True,
        )

    settings = get_settings()
    config = get_config()
    store = ChromaChunkStore(settings.chroma_persist_dir)
    if store.count(grade=grade) == 0:
        print(
            f"No Chroma chunks for grade {grade}. Run scripts/ingest_and_tag_chunks.py first.",
            file=sys.stderr,
        )
        return 1

    llm = build_json_llm()
    embedder = HuggingFaceEmbedder(config.embedding_model)
    candidates = _chapter_spread_candidates(grade)
    if not candidates:
        print(f"No topics in catalog for grade {grade}. Run sync_skill_catalog.", file=sys.stderr)
        return 1

    produced: list[tuple[int, int, Question]] = []
    skipped: list[str] = []
    prior_stems: list[str] = []
    prior_vectors: list[list[float]] = []
    cand_index = 0

    print(
        f"Grade {grade}: generating exactly 10 Aptitude items "
        f"(MCQ/TrueFalse, ABL, {len(candidates)} topic candidates, "
        f"cosine clone ≥ {COSINE_CLONE_MAX})…",
        flush=True,
    )
    for position, abl, qtype in SLOT_PLAN:
        question = None
        while cand_index < len(candidates) and question is None:
            topic_id, chapter, skill = candidates[cand_index]
            cand_index += 1
            chapter_id = normalize_chapter_id(topic_id, grade=grade) or ""
            print(
                f"  slot {position}/10 ABL-{abl} {qtype.value} "
                f"chapter={chapter!r} chapter_id={chapter_id or '-'} topic={topic_id}",
                flush=True,
            )
            candidate = _generate_slot(
                llm=llm,
                store=store,
                embedder=embedder,
                grade=grade,
                position=position,
                baseline_level=abl,
                qtype=qtype,
                topic_id=topic_id,
                chapter=chapter,
                skill=skill,
                top_k=config.retrieval_top_k,
                max_retries=config.generation_max_retries,
                avoid_stems=prior_stems,
            )
            if candidate is None:
                skipped.append(topic_id)
                continue
            text = stem_text(candidate)
            sim = _max_cosine_to_priors(text, prior_vectors, embedder)
            if sim >= COSINE_CLONE_MAX:
                print(
                    f"    skip {topic_id}: paraphrase of an earlier slot "
                    f"(cosine={sim:.3f} ≥ {COSINE_CLONE_MAX})",
                    flush=True,
                )
                skipped.append(topic_id)
                continue
            question = candidate
        if question is None:
            print(
                f"FAIL grade {grade}: could not fill position {position} "
                f"(exhausted {len(candidates)} topic candidates).",
                file=sys.stderr,
            )
            return 2
        produced.append((position, abl, question))
        text = stem_text(question)
        if text:
            prior_stems.append(text)
            prior_vectors.append(embedder.embed([text])[0])
        print(
            f"  [Grade {grade} | {question.chapter_name} | topic={question.topic_id} "
            f"| ABL {abl} | {qtype.value}] -> Generated (approved)",
            flush=True,
        )

    if len(produced) != 10:
        print(f"FAIL grade {grade}: expected 10 items, got {len(produced)}", file=sys.stderr)
        return 2

    repo.replace_amplitude_questions(grade, produced)
    print(f"Grade {grade}: wrote 10 approved Aptitude questions.", flush=True)
    print("  slots:", flush=True)
    for position, abl, question in produced:
        print(
            f"    {position:2d}. ABL-{abl} {question.question_type.value:10s} "
            f"{question.topic_id}  ({question.chapter_name})",
            flush=True,
        )
    if skipped:
        print(f"  skipped {len(skipped)} topic(s): {', '.join(skipped)}", flush=True)
    leftover = len(candidates) - cand_index
    if leftover:
        print(f"  unused topic candidates remaining: {leftover}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grade", type=int, choices=[6, 7, 8, 9], default=None)
    parser.add_argument(
        "--all-grades",
        action="store_true",
        help="Generate grades 6–9 in one run (same as omitting --grade).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing 10-item set for the grade(s).",
    )
    args = parser.parse_args()

    init_schema()
    repo = PostgresAmplitudeRepository(get_session_factory())
    if args.all_grades or args.grade is None:
        grades = [6, 7, 8, 9]
    else:
        grades = [args.grade]

    print(
        f"Aptitude bank LLM: {llm_provider_label()} "
        f"(switch via models.llm_provider in src/iae/config/app.yaml)",
        flush=True,
    )
    worst = 0
    try:
        for grade in grades:
            code = generate_grade(grade=grade, force=args.force, repo=repo)
            worst = max(worst, code)
    except RateLimitExceeded as exc:
        print(f"Stopped on rate limit: {exc}", file=sys.stderr)
        return 3
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
