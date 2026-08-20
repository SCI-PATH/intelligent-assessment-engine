"""One-time helper: derive 3-5 broad sub-concepts per chapter and write them
to ``src/iae/config/subconcepts.yaml``.

The output is intended to be hand-reviewed before running the ingest pipeline.
Re-running for one ``--grade`` replaces that grade's entries only and keeps
other grades intact.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

import yaml
from langchain_community.document_loaders import PyPDFLoader

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from iae.core.curriculum import (
    DEFAULT_GRADE,
    CurriculumConfigError,
    UnknownGradeError,
    get_chapters,
    select_pdf_parts,
)
from iae.core.settings import get_config, get_settings
from iae.infrastructure.llm.groq_client import GroqJsonLlm
from iae.prompts import render

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "src" / "iae" / "config" / "subconcepts.yaml"


def _slugify(name: str) -> str:
    return "-".join(name.lower().split())


def _chapter_text(pdf_path: Path, page_start: int, page_end: int) -> str:
    docs = PyPDFLoader(str(pdf_path)).load()
    pages = [d.page_content for d in docs if page_start - 1 <= d.metadata.get("page", -1) <= page_end - 1]
    return "\n\n".join(pages)


def _load_existing_manifest() -> list[dict]:
    if not OUTPUT_PATH.exists():
        return []
    data = yaml.safe_load(OUTPUT_PATH.read_text(encoding="utf-8")) or {}
    entries = list(data.get("subconcepts") or [])
    for entry in entries:
        entry.setdefault("grade", DEFAULT_GRADE)
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grade",
        type=int,
        default=DEFAULT_GRADE,
        help="Curriculum grade to extract (default: 6).",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Extract only chapters that belong to this configured PDF.",
    )
    parser.add_argument(
        "--pdf-id",
        dest="pdf_id",
        default=None,
        help="Extract only this part id (e.g. part1).",
    )
    args = parser.parse_args()

    try:
        chapters = list(get_chapters(args.grade))
        parts = select_pdf_parts(args.grade, pdf_id=args.pdf_id, pdf_path=args.pdf)
    except (UnknownGradeError, CurriculumConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    subset = bool(args.pdf or args.pdf_id)
    if subset:
        allowed = {part.id for part in parts}
        chapters = [chapter for chapter in chapters if chapter.pdf_id in allowed]

    if not chapters:
        print(
            f"Grade {args.grade} has no chapter page ranges in curriculum.yaml yet.",
            file=sys.stderr,
        )
        return 3

    needed = {chapter.pdf_path for chapter in chapters}
    missing = [path for path in needed if not path.exists()]
    if missing:
        for path in missing:
            print(f"PDF not found: {path}", file=sys.stderr)
        return 1

    settings = get_settings()
    config = get_config()
    llm = GroqJsonLlm(model=config.llm_model, api_key=settings.groq_api_key)

    previous = _load_existing_manifest()
    if subset:
        replaced = {chapter.name for chapter in chapters}
        existing = [
            entry
            for entry in previous
            if int(entry.get("grade", DEFAULT_GRADE)) != args.grade
            or entry.get("chapter_name") not in replaced
        ]
    else:
        existing = [
            entry
            for entry in previous
            if int(entry.get("grade", DEFAULT_GRADE)) != args.grade
        ]
    manifest: list[dict] = []
    for chapter in chapters:
        print(
            f"-> G{args.grade} {chapter.name} "
            f"({chapter.pdf_id} {chapter.pdf_path.name} pp. {chapter.page_start}-{chapter.page_end})"
        )
        excerpt = _chapter_text(chapter.pdf_path, chapter.page_start, chapter.page_end)
        # Trim aggressively: only the first ~12k chars are needed to recover topics.
        prompt = render(
            "subconcepts/extract_subconcepts.jinja",
            chapter_name=chapter.name,
            grade=args.grade,
            context=textwrap.shorten(excerpt, width=12000, placeholder=" ..."),
        )
        result = llm.generate_json(prompt, temperature=0.2)
        for entry in result.get("subconcepts", []):
            name = entry["name"].strip()
            manifest.append(
                {
                    "id": f"g{args.grade}::{_slugify(chapter.name)}::{_slugify(name)}",
                    "grade": args.grade,
                    "chapter_name": chapter.name,
                    "name": name,
                    "description": entry["description"].strip(),
                }
            )

    OUTPUT_PATH.write_text(
        yaml.safe_dump(
            {"subconcepts": existing + manifest},
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {len(manifest)} Grade {args.grade} sub-concepts to {OUTPUT_PATH}")
    print("Review/edit the file before running scripts/ingest_and_tag_chunks.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
