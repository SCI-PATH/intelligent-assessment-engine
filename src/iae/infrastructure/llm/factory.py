from iae.config.settings import get_config, get_settings
from iae.infrastructure.llm.groq_client import GroqJsonLlm
from iae.infrastructure.llm.openai_client import OpenAIJsonLlm


def build_json_llm(*, model: str | None = None, timeout_s: float | None = None):
    """Build the configured JSON LLM.

    Groq uses a single ``GROQ_API_KEY`` and the centralized ``groq_fallbacks``
    chain from ``app.yaml``. The ``model`` argument is ignored for Groq
    (kept for call-site compatibility); OpenAI still honors ``OPENAI_MODEL``.
    """
    settings = get_settings()
    config = get_config()
    provider = settings.llm_provider.lower().strip()

    if provider == "openai":
        openai_model = settings.openai_model or model or config.llm_model
        return OpenAIJsonLlm(model=openai_model, api_key=settings.openai_api_key)

    # default: groq — one key, ordered fallbacks
    return GroqJsonLlm(
        api_key=settings.groq_api_key,
        models=config.groq_fallbacks,
        timeout_s=timeout_s if timeout_s is not None else config.groq_timeout_s,
    )
