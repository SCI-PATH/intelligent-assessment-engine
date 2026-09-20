"""Verify DATABASE_URL reaches Postgres and isolates ``question_engine``.

Usage
-----
    python -m scripts.db.test_connection

Uses the same ``.env`` / settings as the API. Safe against Neon peer schemas
(``learner_analytics``, ``engagement_gaming``, etc.).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import text

from iae.config.settings import get_settings
from iae.infrastructure.postgres.engine import get_engine


def main() -> int:
    settings = get_settings()
    url = settings.database_url
    # Redact password for display
    display = url
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        if "@" in rest and ":" in rest.split("@", 1)[0]:
            userinfo, hostpart = rest.split("@", 1)
            user = userinfo.split(":", 1)[0]
            display = f"{scheme}://{user}:***@{hostpart}"

    print(f"DATABASE_URL = {display}")
    engine = get_engine()
    with engine.connect() as conn:
        schema = conn.execute(text("SHOW search_path")).scalar_one()
        print(f"search_path  = {schema}")
        exists = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.schemata "
                "WHERE schema_name = 'question_engine')"
            )
        ).scalar_one()
        print(f"question_engine schema exists = {exists}")
        if not exists:
            print("FAIL: create schema with: python -m scripts.init_postgres")
            return 1
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'question_engine' "
                "ORDER BY table_name"
            )
        ).scalars().all()
        print(f"tables ({len(tables)}):")
        for name in tables:
            print(f"  - {name}")
        if not tables:
            print("WARN: schema is empty — run: python -m scripts.init_postgres")
            print("PARTIAL_OK (connected; no tables yet)")
            return 0
        if "questions" not in tables:
            print("WARN: questions table missing — run: python -m scripts.init_postgres")
            print("PARTIAL_OK")
            return 0
        qcount = conn.execute(
            text("SELECT COUNT(*) FROM question_engine.questions")
        ).scalar_one()
        print(f"question_engine.questions row count = {qcount}")
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
