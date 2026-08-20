"""Deprecated thin aliases that forward to /api/v1 handlers.

Existing clients using `/assessment/*` and `/teacher/*` keep working during the
sprint. Prefer `/api/v1/...` for new integrations.
"""

from __future__ import annotations

# Legacy routers remain mounted from iae.api.routes.*; this module documents
# the deprecation policy and can hold explicit forwards later if needed.
DEPRECATED_NOTE = (
    "Legacy paths under /assessment/* and /teacher/* are deprecated. "
    "Use /api/v1/amplitude, /api/v1/quizzes, /api/v1/student, /api/v1/teacher."
)
