"""Application configuration loaded from environment + YAML.

Secrets (LLM keys) come from environment variables / .env.
Tunable knobs (max questions, accuracy band, model names) come from
`iae/config/app.yaml` so they can be edited without touching code.

Swap local Postgres for Neon by changing only ``DATABASE_URL`` in ``.env``.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    llm_provider: str = Field(default="groq", alias="LLM_PROVIDER")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    api_base_url: str = Field(default="http://localhost:8001", alias="API_BASE_URL")
    database_url: str = Field(
        default="postgresql+psycopg://iae:iae@localhost:5432/iae",
        alias="DATABASE_URL",
        description="Local or Neon Postgres URL (postgresql+psycopg://...).",
    )
    chroma_persist_dir: str = Field(default="data/chroma_db", alias="CHROMA_PERSIST_DIR")
    skills_xlsx_path: str = Field(
        default="data/skills/Skill-Heirarchies-G6-G9-Full-Chapters.xlsx",
        alias="SKILLS_XLSX_PATH",
    )

    # Peer microservices (empty = always use mock fallbacks)
    component_1_url: str = Field(default="", alias="COMPONENT_1_URL")
    component_3_url: str = Field(default="", alias="COMPONENT_3_URL")
    component_4_url: str = Field(default="", alias="COMPONENT_4_URL")
    # Back-compat alias for Component 4 base URL
    analytics_base_url: str = Field(default="", alias="ANALYTICS_BASE_URL")

    http_client_timeout_s: float = Field(default=3.0, alias="HTTP_CLIENT_TIMEOUT_S")
    debug_agent_log: bool = Field(default=False, alias="DEBUG_AGENT_LOG")

    @property
    def c4_base_url(self) -> str:
        return (self.component_4_url or self.analytics_base_url or "").rstrip("/")


class AppConfig:
    """YAML-backed runtime knobs."""

    def __init__(self, data: dict) -> None:
        self.max_questions: int = int(data["assessment"]["max_questions"])
        self.target_accuracy_lower: float = float(data["assessment"]["target_accuracy_lower"])
        self.target_accuracy_upper: float = float(data["assessment"]["target_accuracy_upper"])
        self.rolling_window: int = int(data["assessment"]["rolling_window"])
        self.cold_start_dok: int = int(data["assessment"]["cold_start_dok"])
        self.response_time_target_seconds: float = float(
            data["assessment"].get("response_time_target_seconds", 45)
        )
        self.post_lesson_max_questions: int = int(
            data.get("assessment", {}).get("post_lesson_max_questions", 15)
        )
        self.amplitude_quiz_size: int = int(data.get("amplitude", {}).get("quiz_size", 10))
        self.amplitude_quiz_weight: float = float(data.get("amplitude", {}).get("quiz_weight", 0.60))
        self.amplitude_history_weight: float = float(
            data.get("amplitude", {}).get("history_weight", 0.40)
        )
        self.embedding_model: str = data["models"]["embedding_model"]
        self.llm_model: str = data["models"]["llm_model"]
        self.llm_grader_model: str = data["models"]["llm_grader_model"]
        self.questions_per_combo: int = int(data["bank"]["questions_per_combo"])
        self.generation_max_retries: int = int(data["bank"]["generation_max_retries"])
        self.retrieval_top_k: int = int(data["bank"]["retrieval_top_k"])


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()


def get_config() -> AppConfig:
    raw = files("iae.config").joinpath("app.yaml").read_text(encoding="utf-8")
    return AppConfig(yaml.safe_load(raw))
