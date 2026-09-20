"""Standalone vs live peer-service identity resolution.

Component 2 stores opaque ``user_id`` / ``grade`` keys from the frontend or
peer services; it does not own the main user profile store.

Today (local testing): accept any non-empty ``user_id`` / ``grade`` injected in
the request body or query. When omitted, fall back to seeded mock users.

Tomorrow (integration): keep the LIVE INTEGRATION blocks as the source of truth
(see root ``INTEGRATION_STEPS.md``).

Seeded users (``python -m scripts.db.seed_mock_users``):
  - mock-student-unassigned  (student, no class)
  - mock-student-class-a     (student, CLASS-A)  ← default student
  - mock-teacher-1           (teacher, CLASS-A)  ← default teacher
"""

from __future__ import annotations

MOCK_STUDENT_UNASSIGNED = "mock-student-unassigned"
MOCK_STUDENT_CLASS_A = "mock-student-class-a"
MOCK_TEACHER_1 = "mock-teacher-1"

STANDALONE_DEFAULT_STUDENT = MOCK_STUDENT_CLASS_A
STANDALONE_DEFAULT_TEACHER = MOCK_TEACHER_1

MOCK_STUDENTS = frozenset({MOCK_STUDENT_UNASSIGNED, MOCK_STUDENT_CLASS_A})
MOCK_TEACHERS = frozenset({MOCK_TEACHER_1})
ALL_MOCK_USERS = MOCK_STUDENTS | MOCK_TEACHERS


def resolve_student_id(incoming: str | None = None) -> str:
    """Student id used for Aptitude / quizzes / history / post-lesson."""
    # --- LIVE INTEGRATION (uncomment for tomorrow — accept real C1/FE/C3 user ids) ---
    # if incoming is not None and str(incoming).strip():
    #     return str(incoming).strip()

    # --- LOCAL TESTING: accept any injected user_id; default to mock if omitted ---
    candidate = (incoming or "").strip()
    if candidate:
        return candidate
    return STANDALONE_DEFAULT_STUDENT


def resolve_teacher_id(incoming: str | None = None) -> str:
    """Teacher id for teacher-hub context (class-scoped bank filters)."""
    # --- LIVE INTEGRATION (uncomment for tomorrow — accept real teacher auth id) ---
    # if incoming is not None and str(incoming).strip():
    #     return str(incoming).strip()

    # --- LOCAL TESTING: accept any injected teacher id; default to mock if omitted ---
    candidate = (incoming or "").strip()
    if candidate:
        return candidate
    return STANDALONE_DEFAULT_TEACHER


def resolve_grade(incoming: int | None = None, *, profile_grade: int | None = None) -> int:
    """Resolve grade for Aptitude / quizzes.

    Priority: request override → stored profile grade → 6.
    """
    # --- LIVE INTEGRATION (uncomment for tomorrow — grade from C1/FE profile) ---
    # if profile_grade is not None and 6 <= int(profile_grade) <= 9:
    #     return int(profile_grade)

    # --- LOCAL TESTING OVERRIDE (active today) ---
    if incoming is not None and 6 <= int(incoming) <= 9:
        return int(incoming)
    if profile_grade is not None and 6 <= int(profile_grade) <= 9:
        return int(profile_grade)
    return 6


def resolve_terminate_actor(source: str | None = None) -> str:
    """Label for who triggered kill-switch (audit / terminate_reason prefix)."""
    # --- LIVE INTEGRATION (uncomment for tomorrow — trust C3 source header/body) ---
    # if source is not None and str(source).strip():
    #     return str(source).strip()

    # --- LOCAL TESTING ---
    candidate = (source or "").strip()
    return candidate or "component_3"
