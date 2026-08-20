"""PDF -> tagged ``Chunk`` objects.

We deliberately keep loading and chapter assignment in the same module so the
relationship between PDF page numbers and the curriculum table is obvious.
Sub-concept assignment is delegated to ``chunk_tagger`` which depends only on
embeddings.

A grade may span several PDFs (Part 1 / Part 2). Page numbers are 1-based
inside each file and must not be mixed across parts.
"""

from __future__ import annotations

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from iae.core.curriculum import (
    DEFAULT_GRADE,
    PdfPart,
    chapter_for_page,
    get_grade_pdf_parts,
)
from iae.core.models import Chunk

DEFAULT_CHUNK_SIZE = 900
DEFAULT_CHUNK_OVERLAP = 150


def load_and_chunk_pdf(
    pdf_path: str | Path,
    *,
    grade: int = DEFAULT_GRADE,
    pdf_id: str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Return chunks tagged with chapter + page range, sub-concept blank.

    ``PyPDFLoader`` exposes 0-based page indices via ``metadata['page']``;
    we convert them to 1-based to align with the curriculum mapping.
    Chunks that fall outside any chapter range (front matter, indices) are
    dropped silently.

    ``pdf_id`` selects the matching chapter ranges when the grade has more
    than one textbook PDF. If omitted, the path is matched against
    ``curriculum.yaml``.
    """
    path = Path(pdf_path)
    resolved_id = pdf_id or _pdf_id_for_path(grade, path)
    loader = PyPDFLoader(str(path))
    documents = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    split_docs = splitter.split_documents(documents)

    chunks: list[Chunk] = []
    for doc in split_docs:
        page = int(doc.metadata.get("page", 0)) + 1
        chapter = chapter_for_page(page, grade=grade, pdf_id=resolved_id, source=path)
        if chapter is None:
            continue
        text = doc.page_content.strip()
        if len(text) < 80:
            continue
        chunks.append(
            Chunk(
                text=text,
                chapter_name=chapter,
                sub_concept="UNASSIGNED",
                page_start=page,
                page_end=page,
                source=path.name,
                grade=grade,
            )
        )
    return chunks


def load_and_chunk_grade(
    grade: int = DEFAULT_GRADE,
    *,
    parts: list[PdfPart] | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Load every configured PDF for ``grade`` and concatenate tagged chunks."""
    selected = parts if parts is not None else list(get_grade_pdf_parts(grade))
    chunks: list[Chunk] = []
    for part in selected:
        chunks.extend(
            load_and_chunk_pdf(
                part.path,
                grade=grade,
                pdf_id=part.id,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        )
    return chunks


def _pdf_id_for_path(grade: int, pdf_path: Path) -> str | None:
    target = pdf_path.name
    for part in get_grade_pdf_parts(grade):
        if part.path.name == target or part.path == pdf_path:
            return part.id
    return None
