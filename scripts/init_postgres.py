"""Create the ``question_engine`` schema and tables.

Uses ``DATABASE_URL`` from ``.env``. Apply after Postgres is running::

    python -m scripts.init_postgres
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from iae.infrastructure.postgres.engine import get_engine, init_schema


def main() -> int:
    init_schema()
    print(f"Applied question_engine schema on {get_engine().url.render_as_string(hide_password=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
