"""Peer microservice base URLs and path constants.

Hardcoded hosts — edit THIS FILE for deployment (do not use .env for peer URLs).

Local placeholders (Component 2 itself runs on :8001):
  Component 1 (Lesson Engine)     → :8002
  Component 3 (Engagement)        → :8003
  Component 4 (Learner Analytics) → :8004

Set ``PEER_HTTP_LIVE = True`` only when those services are actually reachable.
While False, feature services return hardcoded mock JSON (httpx blocks stay
commented beside the mocks for one-line live activation).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Deploy: replace these three strings with production base URLs.
# ---------------------------------------------------------------------------
COMPONENT_1_URL = "http://localhost:8002"
COMPONENT_3_URL = "http://localhost:8003"
COMPONENT_4_URL = "http://localhost:8004"

# False → hardcoded mocks in diagnostic_quiz / peer clients.
# True  → uncommented httpx calls against the URLs above.
PEER_HTTP_LIVE = False

# Outbound path constants (peers own these routes; no host/port here)
C4_BKT_SNAPSHOT_PATH = "/api/v1/quiz/bkt-snapshot"
C4_ASSESSMENT_SUBMIT_PATH = "/api/v1/assessment-submit"
C1_QUIZ_READY_PATH = "/api/v1/lessons/quiz-ready"
C3_SESSION_TERMINATED_PATH = "/api/v1/engagement/session-terminated"


def component_1_base_url() -> str:
    return COMPONENT_1_URL.rstrip("/")


def component_3_base_url() -> str:
    return COMPONENT_3_URL.rstrip("/")


def component_4_base_url() -> str:
    return COMPONENT_4_URL.rstrip("/")


def join_url(base: str, path: str) -> str:
    """Join base URL and absolute path without duplicating slashes."""
    base = (base or "").rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"
