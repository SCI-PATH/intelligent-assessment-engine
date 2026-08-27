"""Groq-backed JSON LLM adapter implementing ``ILlmJson``.

Tries a centralized fallback chain of models on a single ``GROQ_API_KEY``.
The wrapper enforces strict JSON via LangChain's ``JsonOutputParser``.
"""

from __future__ import annotations

import logging
from typing import Sequence

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)

# Defaults match app.yaml; factory passes the configured list.
DEFAULT_GROQ_FALLBACKS: tuple[str, ...] = (
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "llama-3.1-8b-instant",
)


class GroqJsonLlm:
    """Concrete ``ILlmJson`` using Groq with ordered model fallbacks."""

    def __init__(
        self,
        *,
        api_key: str,
        models: Sequence[str] | None = None,
        model: str | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is missing in the environment.")
        if models:
            chain = [m.strip() for m in models if m and str(m).strip()]
        elif model:
            chain = [model.strip()]
        else:
            chain = list(DEFAULT_GROQ_FALLBACKS)
        if not chain:
            chain = list(DEFAULT_GROQ_FALLBACKS)
        self._models = chain
        self._api_key = api_key
        self._timeout_s = float(timeout_s)
        self._parser = JsonOutputParser()
        self._clients: dict[str, ChatGroq] = {}

    @property
    def models(self) -> list[str]:
        return list(self._models)

    def _client_for(self, model_name: str, *, temperature: float) -> ChatGroq:
        # Keyed by model+temperature so grader (cool) and generator (warm) stay separate.
        key = f"{model_name}|{temperature:.2f}"
        cached = self._clients.get(key)
        if cached is not None:
            return cached
        llm = ChatGroq(
            temperature=temperature,
            model_name=model_name,
            groq_api_key=self._api_key,
            request_timeout=self._timeout_s,
        )
        self._clients[key] = llm
        return llm

    def generate_json(self, prompt: str, *, temperature: float = 0.3) -> dict:
        template = PromptTemplate.from_template("{rendered}")
        last_error: Exception | None = None
        for index, model_name in enumerate(self._models):
            try:
                bound = self._client_for(model_name, temperature=temperature)
                chain = template | bound | self._parser
                result = chain.invoke({"rendered": prompt})
                if not isinstance(result, dict):
                    raise ValueError(f"Groq model {model_name} returned non-object JSON")
                if index > 0:
                    logger.info("Groq fallback succeeded model=%s (slot=%s)", model_name, index + 1)
                return result
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Groq model failed model=%s slot=%s/%s err=%s",
                    model_name,
                    index + 1,
                    len(self._models),
                    exc,
                )
                continue
        raise RuntimeError(
            f"All Groq models failed ({', '.join(self._models)}): {last_error}"
        ) from last_error
