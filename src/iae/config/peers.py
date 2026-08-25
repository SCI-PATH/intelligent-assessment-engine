"""Peer microservice base URLs and path constants.

Hardcoded hosts — edit THIS FILE for deployment (do not use .env for peer URLs).

Local vs deployed (port map):
  Component 1 (Lesson Engine)     → :8000  → http://3.6.20.31:8000
  User Management (not called here) → :8001 → http://3.6.20.31:8001
  Component 3 (Engagement / Gaming) → :8002 → http://3.6.20.31:8002
  Component 4 (Learner Analytics) → :8003  → http://52.66.167.213:8003
  Component 2 (this service)      → :8004  → http://43.204.6.115:8004

Per-peer live flags: try the deployed host first, fall back to hardcoded mock
on timeout / HTTP error. ``PEER_HTTP_LIVE`` is the default for C1 / C3.
C4 (:8003) is live now; turn the others on the same way when they are reachable.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Deploy: production / EC2 base URLs (port identifies the service).
# For pure local peers, swap back to http://localhost:PORT.
# ---------------------------------------------------------------------------
COMPONENT_1_URL = "http://3.6.20.31:8000"
COMPONENT_3_URL = "http://3.6.20.31:8002"
COMPONENT_4_URL = "http://52.66.167.213:8003"

# False → hardcoded mocks in peer clients.
# True  → live httpx against the URLs above (falls back to mock on error).
PEER_HTTP_LIVE = False
C4_HTTP_LIVE = True  # deployed :8003 first; mock fallback if C4 is down

# Outbound path constants (peers own these routes; no host/port here)
C4_BKT_SNAPSHOT_PATH = "/api/v1/quiz/bkt-snapshot"
C4_ASSESSMENT_SUBMIT_PATH = "/api/v1/assessment-submit"
C1_QUIZ_READY_PATH = "/api/v1/lessons/quiz-ready"
# C1 returns the chapter just completed / active for post-lesson scoping.
# Confirm path with Lesson Engine; mock shape is stable on this side.
C1_ACTIVE_CHAPTER_PATH = "/api/v1/lessons/active-chapter"
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
