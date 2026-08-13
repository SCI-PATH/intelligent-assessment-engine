"""PDF -> tagged chunks (legacy Mongo write still used until Phase 3).

Run after ``scripts/extract_subconcepts.py`` has produced (and you have
reviewed) ``src/iae/config/subconcepts.yaml``. PDF path and chapter page
ranges are read from ``curriculum.yaml`` for the selected ``--grade``.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from iae.core.curriculum import (
    DEFAULT_GRADE,
    UnknownGradeError,
    get_chapters,
    get_grade_pdf_path,
    get_subconcepts,
)
from iae.core.settings import get_config
from iae.infrastructure.mongo.chunks_repo import MongoChunkRepository
from iae.infrastructure.mongo.client import ensure_indexes, get_database
from iae.infrastructure.rag.chunk_tagger import assign_subconcepts
from iae.infrastructure.rag.embeddings import HuggingFaceEmbedder
from iae.infrastructure.rag.pdf_loader import load_and_chunk_pdf


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

    print(f"Loading and splitting {pdf_path} (grade {args.grade})...")
    chunks = load_and_chunk_pdf(pdf_path, grade=args.grade)
    print(f"Produced {len(chunks)} chapter-tagged chunks.")

    print("Embedding chunks and assigning sub-concepts...")
    embedder = HuggingFaceEmbedder(get_config().embedding_model)
    chunks = assign_subconcepts(chunks, embedder)

    db = get_database()
    ensure_indexes(db)
    repo = MongoChunkRepository(db)
    written = repo.replace_all(chunks)

    summary: Counter[tuple[int, str, str]] = Counter(
        (c.grade, c.chapter_name, c.sub_concept) for c in chunks
    )
    print(f"\nWrote {written} chunks to Mongo. Coverage:")
    for (grade, chapter, sub), count in sorted(summary.items()):
        print(f"  G{grade}  {chapter:40s}  {sub:30s}  {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
