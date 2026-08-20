"""Idempotent seed of three mock users for Streamlit / local demos.

Users
-----
- mock-student-unassigned — student, no class code
- mock-student-class-a    — student, class_code=CLASS-A
- mock-teacher-1          — teacher, owns CLASS-A
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from iae.core.models import UserRole
from iae.infrastructure.postgres.amplitude_repo import PostgresAmplitudeRepository
from iae.infrastructure.postgres.engine import get_session_factory, init_schema


MOCK_USERS = [
    {
        "user_id": "mock-student-unassigned",
        "role": UserRole.STUDENT,
        "display_name": "Unassigned Student",
        "class_code": None,
        "grade": 7,
    },
    {
        "user_id": "mock-student-class-a",
        "role": UserRole.STUDENT,
        "display_name": "Class A Student",
        "class_code": "CLASS-A",
        "grade": 7,
    },
    {
        "user_id": "mock-teacher-1",
        "role": UserRole.TEACHER,
        "display_name": "Teacher One",
        "class_code": "CLASS-A",
        "grade": None,
    },
]


def main() -> int:
    init_schema()
    store = PostgresAmplitudeRepository(get_session_factory())
    for user in MOCK_USERS:
        profile = store.upsert_user(**user)
        print(f"upserted {profile.user_id} role={profile.role.value} class={profile.class_code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
