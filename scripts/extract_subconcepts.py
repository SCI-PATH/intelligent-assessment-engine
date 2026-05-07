"""One-time helper: derive 3-5 broad sub-concepts per chapter and write them
to ``src/iae/config/subconcepts.yaml``.

The output is intended to be hand-reviewed before running the ingest pipeline.
Re-running the script overwrites the file, so make local edits *after* the
final run.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

import yaml
from langchain_community.document_loaders import PyPDFLoader

from iae.core.curriculum import get_chapters
from iae.core.settings import get_config, get_settings
from iae.infrastructure.llm.groq_client import GroqJsonLlm
from iae.prompts import render

DEFAULT_PDF = Path("data/grade_6_science.pdf")
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "src" / "iae" / "config" / "subconcepts.yaml"


def _slugify(name: str) -> str:
    return "-".join(name.lower().split())


def _chapter_text(pdf_path: Path, page_start: int, page_end: int) -> str:
    docs = PyPDFLoader(str(pdf_path)).load()
    pages = [d.page_content for d in docs if page_start - 1 <= d.metadata.get("page", -1) <= page_end - 1]
    return "\n\n".join(pages)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 1

    settings = get_settings()
    config = get_config()
    llm = GroqJsonLlm(model=config.llm_model, api_key=settings.groq_api_key)

    manifest: list[dict] = []
    for chapter in get_chapters():
        print(f"-> {chapter.name} (pp. {chapter.page_start}-{chapter.page_end})")
        excerpt = _chapter_text(args.pdf, chapter.page_start, chapter.page_end)
        # Trim aggressively: only the first ~12k chars are needed to recover topics.
        prompt = render(
            "subconcepts/extract_subconcepts.jinja",
            chapter_name=chapter.name,
            context=textwrap.shorten(excerpt, width=12000, placeholder=" ..."),
        )
        result = llm.generate_json(prompt, temperature=0.2)
        for entry in result.get("subconcepts", []):
            name = entry["name"].strip()
            manifest.append(
                {
                    "id": f"{_slugify(chapter.name)}::{_slugify(name)}",
                    "chapter_name": chapter.name,
                    "name": name,
                    "description": entry["description"].strip(),
                }
            )

    OUTPUT_PATH.write_text(
        yaml.safe_dump({"subconcepts": manifest}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"\nWrote {len(manifest)} sub-concepts to {OUTPUT_PATH}")
    print("Review/edit the file before running scripts/ingest_and_tag_chunks.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
