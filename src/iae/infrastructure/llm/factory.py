from iae.config.settings import get_settings
from iae.infrastructure.llm.groq_client import GroqJsonLlm
from iae.infrastructure.llm.openai_client import OpenAIJsonLlm


def build_json_llm(*, model: str):
    settings = get_settings()
    provider = settings.llm_provider.lower().strip()

    if provider == "openai":
        openai_model = settings.openai_model or model
        return OpenAIJsonLlm(model=openai_model, api_key=settings.openai_api_key)

    # default: groq
    return GroqJsonLlm(model=model, api_key=settings.groq_api_key)
