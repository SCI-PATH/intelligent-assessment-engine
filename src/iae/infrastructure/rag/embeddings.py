"""HuggingFace sentence-transformer adapter implementing ``IEmbedder``.

The model is loaded lazily so that simply importing this module does not
download weights at API startup.
"""

from __future__ import annotations

from langchain_huggingface import HuggingFaceEmbeddings


class HuggingFaceEmbedder:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._impl: HuggingFaceEmbeddings | None = None

    def _ensure_model(self) -> HuggingFaceEmbeddings:
        if self._impl is None:
            self._impl = HuggingFaceEmbeddings(model_name=self._model_name)
        return self._impl

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._ensure_model().embed_documents(texts)
