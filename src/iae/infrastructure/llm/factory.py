from iae.config.settings import get_config, get_settings
from iae.infrastructure.llm.groq_client import GroqJsonLlm
from iae.infrastructure.llm.openai_client import OpenAIJsonLlm


def build_json_llm(*, model: str | None = None, timeout_s: float | None = None):
    """Build the configured JSON LLM.

    Provider is controlled by ``models.llm_provider`` in ``app.yaml`` (one-line
    switch between ``openai`` and ``groq``). API keys remain in ``.env`` only.

    Groq uses the centralized ``groq_fallbacks`` chain from ``app.yaml``.
    OpenAI uses ``models.openai_model`` (defaults to ``gpt-4o-mini``).
    """
    settings = get_settings()
    config = get_config()
    provider = config.llm_provider

    if provider == "openai":
        openai_model = config.openai_model or settings.openai_model or model or "gpt-4o-mini"
        resolved_timeout = (
            timeout_s if timeout_s is not None else config.openai_timeout_s
        )
        return OpenAIJsonLlm(
            model=openai_model,
            api_key=settings.openai_api_key,
            timeout_s=resolved_timeout,
        )

    if provider != "groq":
        raise RuntimeError(
            f"Unsupported models.llm_provider={provider!r} in app.yaml "
            "(expected 'openai' or 'groq')."
        )

    resolved_timeout = timeout_s if timeout_s is not None else config.groq_timeout_s
    return GroqJsonLlm(
        api_key=settings.groq_api_key,
        models=config.groq_fallbacks,
        timeout_s=resolved_timeout,
    )


def llm_provider_label() -> str:
    """Human-readable active provider + model for logging."""
    config = get_config()
    if config.llm_provider == "openai":
        return f"openai/{config.openai_model}"
    fallbacks = config.groq_fallbacks
    chain = " → ".join(fallbacks) if fallbacks else "(none)"
    return f"groq [{chain}]"
