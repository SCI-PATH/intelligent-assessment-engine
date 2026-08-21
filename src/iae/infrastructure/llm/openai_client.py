import json
from openai import OpenAI


class OpenAIJsonLlm:
    """OpenAI-backed JSON LLM adapter implementing ILlmJson."""

    def __init__(self, *, model: str, api_key: str, timeout_s: float = 90.0) -> None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing in the environment.")
        self._model = model
        self._client = OpenAI(api_key=api_key, timeout=timeout_s)

    def generate_json(self, prompt: str, *, temperature: float = 0.3) -> dict:
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
