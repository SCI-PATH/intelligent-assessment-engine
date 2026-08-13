"""PDF -> Chroma ``curriculum_chunks`` collection.

Run after ``scripts/extract_subconcepts.py`` and ``scripts/sync_skill_catalog.py``.
PDF path and chapter page ranges come from ``curriculum.yaml`` for ``--grade``.
Re-running a grade deletes only that grade's Chroma vectors.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from iae.core.curriculum import (
    DEFAULT_GRADE,
    UnknownGradeError,
    get_chapters,
    get_grade_pdf_path,
    get_subconcepts,
)
from iae.core.settings import get_config
from iae.core.skills import get_topics, match_curriculum_chapters
from iae.infrastructure.rag.chroma_store import ChromaChunkStore
from iae.infrastructure.rag.chunk_tagger import assign_subconcepts
from iae.infrastructure.rag.embeddings import HuggingFaceEmbedder
from iae.infrastructure.rag.pdf_loader import load_and_chunk_pdf
from iae.infrastructure.rag.topic_tagger import assign_topic_ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grade",
        type=int,
        default=DEFAULT_GRADE,
        help="Curriculum grade to ingest (default: 6).",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Override the PDF path from curriculum.yaml.",
    )
    args = parser.parse_args()

    try:
        pdf_path = args.pdf or get_grade_pdf_path(args.grade)
        chapters = get_chapters(args.grade)
    except UnknownGradeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not chapters:
        print(
            f"Grade {args.grade} has no chapter page ranges in curriculum.yaml yet. "
            "Fill page_start/page_end from the PDF Table of Contents first.",
            file=sys.stderr,
        )
        return 3

    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1
    if not get_subconcepts():
        print(
            "subconcepts.yaml is empty. Run scripts/extract_subconcepts.py first.",
            file=sys.stderr,
        )
        return 2
    if not get_topics():
        print(
            "Topic catalog is empty. Run scripts/sync_skill_catalog.py first.",
            file=sys.stderr,
        )
        return 2

    matched, unmatched = match_curriculum_chapters(args.grade)
    print(f"Excel Topic IDs matched {len(matched)} curriculum chapters.")
    for title in unmatched:
        print(f"  unmatched Excel chapter (no PDF map yet): {title}")

    print(f"Loading and splitting {pdf_path} (grade {args.grade})...")
    chunks = load_and_chunk_pdf(pdf_path, grade=args.grade)
    print(f"Produced {len(chunks)} chapter-tagged chunks.")

    print("Embedding chunks and assigning sub-concepts + Topic IDs...")
    embedder = HuggingFaceEmbedder(get_config().embedding_model)
    chunks = assign_subconcepts(chunks, embedder)
    chunks = assign_topic_ids(chunks, embedder)

    print("Writing embeddings to Chroma...")
    embeddings = embedder.embed([chunk.text for chunk in chunks])
    store = ChromaChunkStore()
    written = store.replace_grade(args.grade, chunks, embeddings)

    summary: Counter[tuple[int, str, str]] = Counter(
        (c.grade, c.chapter_name, c.topic_id or "(none)") for c in chunks
    )
    print(f"\nWrote {written} chunks to Chroma (grade {args.grade} replaced). Coverage:")
    for (grade, chapter, topic_id), count in sorted(summary.items()):
        print(f"  G{grade}  {chapter:40s}  {topic_id:22s}  {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
