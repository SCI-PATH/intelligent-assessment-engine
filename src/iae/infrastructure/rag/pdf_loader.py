"""PDF -> tagged ``Chunk`` objects.

We deliberately keep loading and chapter assignment in the same module so the
relationship between PDF page numbers and the curriculum table is obvious.
Sub-concept assignment is delegated to ``chunk_tagger`` which depends only on
embeddings.
"""

from __future__ import annotations

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from iae.core.curriculum import DEFAULT_GRADE, chapter_for_page
from iae.core.models import Chunk

DEFAULT_CHUNK_SIZE = 900
DEFAULT_CHUNK_OVERLAP = 150


def load_and_chunk_pdf(
    pdf_path: str | Path,
    *,
    grade: int = DEFAULT_GRADE,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Return chunks tagged with chapter + page range, sub-concept blank.

    ``PyPDFLoader`` exposes 0-based page indices via ``metadata['page']``;
    we convert them to 1-based to align with the curriculum mapping.
    Chunks that fall outside any chapter range (front matter, indices) are
    dropped silently.
    """
    loader = PyPDFLoader(str(pdf_path))
    documents = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    split_docs = splitter.split_documents(documents)

    chunks: list[Chunk] = []
    for doc in split_docs:
        page = int(doc.metadata.get("page", 0)) + 1
        chapter = chapter_for_page(page, grade=grade)
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
                source=Path(pdf_path).name,
                grade=grade,
            )
        )
    return chunks
