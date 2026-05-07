"""PDF -> Mongo ``chunks`` collection.

Run after ``scripts/extract_subconcepts.py`` has produced (and you have
reviewed) ``src/iae/config/subconcepts.yaml``. Re-running wipes and rewrites
the collection so you always get a clean snapshot of the current curriculum.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from iae.core.curriculum import get_subconcepts
from iae.core.settings import get_config
from iae.infrastructure.mongo.chunks_repo import MongoChunkRepository
from iae.infrastructure.mongo.client import ensure_indexes, get_database
from iae.infrastructure.rag.chunk_tagger import assign_subconcepts
from iae.infrastructure.rag.embeddings import HuggingFaceEmbedder
from iae.infrastructure.rag.pdf_loader import load_and_chunk_pdf

DEFAULT_PDF = Path("data/grade_6_science.pdf")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 1
    if not get_subconcepts():
        print(
            "subconcepts.yaml is empty. Run scripts/extract_subconcepts.py first.",
            file=sys.stderr,
        )
        return 2

    print(f"Loading and splitting {args.pdf}...")
    chunks = load_and_chunk_pdf(args.pdf)
    print(f"Produced {len(chunks)} chapter-tagged chunks.")

    print("Embedding chunks and assigning sub-concepts...")
    embedder = HuggingFaceEmbedder(get_config().embedding_model)
    chunks = assign_subconcepts(chunks, embedder)

    db = get_database()
    ensure_indexes(db)
    repo = MongoChunkRepository(db)
    written = repo.replace_all(chunks)

    summary: Counter[tuple[str, str]] = Counter((c.chapter_name, c.sub_concept) for c in chunks)
    print(f"\nWrote {written} chunks to Mongo. Coverage:")
    for (chapter, sub), count in sorted(summary.items()):
        print(f"  {chapter:40s}  {sub:30s}  {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
