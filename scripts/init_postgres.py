"""Create the ``question_engine`` schema and ``questions`` table.

Prereq (local Docker)::

    docker run --name iae-postgres -e POSTGRES_USER=iae -e POSTGRES_PASSWORD=iae -e POSTGRES_DB=iae -p 5432:5432 -d postgres:16

Then set DATABASE_URL=postgresql+psycopg://iae:iae@localhost:5432/iae
"""

from __future__ import annotations

from iae.infrastructure.postgres.engine import get_engine, init_schema


def main() -> int:
    init_schema()
    print(f"Applied question_engine schema on {get_engine().url.render_as_string(hide_password=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
