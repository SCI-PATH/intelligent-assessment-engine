"""Groq-backed JSON LLM adapter implementing ``ILlmJson``.

The wrapper enforces strict JSON: it pipes ``ChatGroq`` through LangChain's
``JsonOutputParser`` so callers always get a parsed ``dict`` and never have to
worry about stray markdown fences in the model output.
"""

from __future__ import annotations

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq


class GroqJsonLlm:
    """Concrete ``ILlmJson`` using Groq's hosted llama models."""

    def __init__(self, *, model: str, api_key: str) -> None:
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is missing in the environment.")
        self._model = model
        self._api_key = api_key
        self._parser = JsonOutputParser()

    def generate_json(self, prompt: str, *, temperature: float = 0.3) -> dict:
        llm = ChatGroq(
            temperature=temperature,
            model_name=self._model,
            groq_api_key=self._api_key,
        )
        # Wrap the rendered prompt so LangChain treats it as a literal template
        # without re-interpreting curly braces in JSON examples.
        template = PromptTemplate.from_template("{rendered}")
        chain = template | llm | self._parser
        return chain.invoke({"rendered": prompt})
