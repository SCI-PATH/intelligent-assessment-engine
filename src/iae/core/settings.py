"""Application configuration loaded from environment + YAML.

Secrets (Mongo URI, LLM keys) come from environment variables / .env.
Tunable knobs (max questions, accuracy band, model names) come from
`iae/config/app.yaml` so they can be edited without touching code.
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

    mongodb_uri: str = Field(default="", alias="MONGODB_URI")
    mongodb_db_name: str = Field(default="iae", alias="MONGODB_DB_NAME")
    api_base_url: str = Field(default="http://localhost:8001", alias="API_BASE_URL")
    chroma_persist_dir: str = Field(default="data/chroma_db", alias="CHROMA_PERSIST_DIR")
    skills_xlsx_path: str = Field(
        default="data/skills/Skill-Heirarchies-G6-G9-Full-Chapters.xlsx",
        alias="SKILLS_XLSX_PATH",
    )


class AppConfig:
    """YAML-backed runtime knobs."""

    def __init__(self, data: dict) -> None:
        self.max_questions: int = int(data["assessment"]["max_questions"])
        self.target_accuracy_lower: float = float(data["assessment"]["target_accuracy_lower"])
        self.target_accuracy_upper: float = float(data["assessment"]["target_accuracy_upper"])
        self.rolling_window: int = int(data["assessment"]["rolling_window"])
        self.cold_start_dok: int = int(data["assessment"]["cold_start_dok"])
        self.response_time_target_seconds: float = float(data["assessment"].get("response_time_target_seconds", 45))
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
