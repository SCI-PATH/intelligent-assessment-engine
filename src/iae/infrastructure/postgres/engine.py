"""SQLAlchemy engine + schema bootstrap for the ``question_engine`` schema."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from iae.core.settings import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to .env "
            "(example: postgresql+psycopg://iae:iae@localhost:5432/iae)."
        )
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)


def init_schema(engine: Engine | None = None) -> None:
    """Apply ``schema.sql`` (idempotent CREATE IF NOT EXISTS)."""
    sql = files("iae.infrastructure.postgres").joinpath("schema.sql").read_text(encoding="utf-8")
    target = engine or get_engine()
    statements = [part.strip() for part in sql.split(";") if part.strip()]
    with target.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
