"""Generate exactly 10 Amplitude placement questions per grade (MCQ / TrueFalse).

Uses Amplitude Baseline Ladder (ABL-1 Recall, ABL-2 Apply, ABL-3 Connect).
Writes only to ``question_engine.amplitude_questions`` (status=approved).
Does NOT touch the adaptive ``questions`` bank.

Usage
-----
    python -m scripts.generate_amplitude_bank
    python -m scripts.generate_amplitude_bank --grade 7
    python -m scripts.generate_amplitude_bank --grade 6 --force
"""

from __future__ import annotations

import argparse
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
    retrieve_chunks,
)
from iae.config.settings import get_config, get_settings
from iae.domain.models import Question, QuestionOrigin, QuestionStatus, QuestionType
from iae.domain.skills import get_topic, topics_for_grade
from iae.infrastructure.llm.factory import build_json_llm
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

# Exactly 10 slots planned up front (position, ABL level, question type).
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


def _topic_plan(grade: int) -> list[tuple[str, str, str]]:
    """Return 10 (topic_id, chapter_name, skill) tuples spanning the grade syllabus."""
    topics = topics_for_grade(grade)
    if not topics:
        raise RuntimeError(f"No topics in catalog for grade {grade}. Run sync_skill_catalog.")
    topics = sorted(topics, key=lambda t: (t.chapter_title or "", t.topic_id))
    assigned: list[tuple[str, str, str]] = []
    for index in range(10):
        topic = topics[index % len(topics)]
        chapter = curriculum_chapter_for_topic(topic.chapter_title, grade)
        assigned.append((topic.topic_id, chapter, topic.skill or ""))
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
) -> Question | None:
    topic = get_topic(topic_id)
    if topic is None:
        print(f"  ! position {position}: unknown topic {topic_id}", file=sys.stderr)
        return None
    chunks = retrieve_chunks(
        store=store,
        embedder=embedder,
        grade=grade,
        chapter=chapter,
        topic_ids=[topic_id],
        top_k=top_k,
    )
    if not chunks:
        print(f"  ! position {position}: no Chroma chunks for {topic_id}", file=sys.stderr)
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
    )
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            raw = llm.generate_json(prompt, temperature=0.55)
            payload = build_payload(qtype, raw)
            return Question(
                chapter_name=chapter,
                sub_concept=skill or topic.skill or "Amplitude",
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
    print(f"  ! position {position} ABL-{baseline_level} {qtype.value} failed: {last_error}", file=sys.stderr)
    return None


def generate_grade(*, grade: int, force: bool, repo: PostgresAmplitudeRepository) -> int:
    existing = repo.count_amplitude_questions(grade)
    if existing == 10 and not force:
        print(f"Grade {grade}: already has 10 Amplitude items — skip (use --force to regenerate).")
        return 0
    if existing and force:
        print(f"Grade {grade}: regenerating (--force); replacing {existing} items.")

    settings = get_settings()
    config = get_config()
    store = ChromaChunkStore(settings.chroma_persist_dir)
    if store.count(grade=grade) == 0:
        print(
            f"No Chroma chunks for grade {grade}. Run scripts/ingest_and_tag_chunks.py first.",
            file=sys.stderr,
        )
        return 1

    llm = build_json_llm(model=config.llm_model)
    embedder = HuggingFaceEmbedder(config.embedding_model)
    topics = _topic_plan(grade)
    produced: list[tuple[int, int, Question]] = []

    print(f"Grade {grade}: generating exactly 10 Amplitude items (MCQ/TrueFalse, ABL)…")
    for (position, abl, qtype), (topic_id, chapter, skill) in zip(SLOT_PLAN, topics):
        print(f"  slot {position}/10 ABL-{abl} {qtype.value} topic={topic_id}")
        question = _generate_slot(
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
        )
        if question is None:
            print(f"FAIL grade {grade}: could not generate position {position}", file=sys.stderr)
            return 2
        produced.append((position, abl, question))

    if len(produced) != 10:
        print(f"FAIL grade {grade}: expected 10 items, got {len(produced)}", file=sys.stderr)
        return 2

    repo.replace_amplitude_questions(grade, produced)
    print(f"Grade {grade}: wrote 10 approved Amplitude questions.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grade", type=int, choices=[6, 7, 8, 9], default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing 10-item set for the grade(s).",
    )
    args = parser.parse_args()

    init_schema()
    repo = PostgresAmplitudeRepository(get_session_factory())
    grades = [args.grade] if args.grade else [6, 7, 8, 9]
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
