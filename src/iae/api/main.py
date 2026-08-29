"""FastAPI application factory — Intelligent Assessment Engine (Component 2)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from iae.api.bootstrap import build_container
from iae.api.request_logging import RequestResponseLoggingMiddleware
from iae.api.routes import amplitude, health, history, quizzes, teacher
from iae.config.settings import get_settings

OPENAPI_TAGS = [
    {"name": "Health", "description": "Liveness probe."},
    {
        "name": "Aptitude Diagnostic Test",
        "description": (
            "Pre-use placement: chapters multi-select + mandatory past marks survey, "
            "fixed 10 MCQ/TrueFalse quiz (amplitude_questions), "
            "then BASIC | INTERMEDIATE | ADVANCED. "
            "See GET /amplitude/chapters and docs/FRONTEND_INTEGRATION.md."
        ),
    },
    {
        "name": "Quizzes and Testing Loops",
        "description": (
            "Customizable / post-lesson multivariate Elo DDA. "
            "Outbound C4: BKT snapshot + assessment-submit. "
            "Peer hosts in iae.config.peers."
        ),
    },
    {"name": "Student History", "description": "Session list, detail, LLM analysis."},
    {"name": "Teacher Hub", "description": "Generate / approve / reject bank items."},
]

API_DESCRIPTION = """
# Intelligent Assessment Engine (Component 2)

Clean layered architecture: `api` → `application` → `domain` / `adaptive` / `infrastructure`.

**Inbound prefix:** `/api/v1/assessment-engine`

**Frontend UI contract (screens, dropdowns, all endpoints):** [`docs/FRONTEND_INTEGRATION.md`](docs/FRONTEND_INTEGRATION.md)

Peer URLs are hardcoded in `src/iae/config/peers.py` (`C1 :8000`, `C3 :8002`, `C4 :8003` deployed hosts).
C1 is live for post-lesson chapter resolve (`C1_HTTP_LIVE`, fallback `G6_C8`); C4 is live (`C4_HTTP_LIVE`); C3 stays mocked until `PEER_HTTP_LIVE = True`.

**Base URL (local):** `http://localhost:8004` · Docs: [`/docs`](/docs)
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.container = build_container()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.log_http_payloads:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            force=True,
        )
        logging.getLogger("iae.http").setLevel(logging.INFO)

    app = FastAPI(
        title="Intelligent Assessment Engine",
        version="0.6.0",
        description=API_DESCRIPTION,
        lifespan=lifespan,
        openapi_tags=OPENAPI_TAGS,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "IAE Research Project — Component 2"},
        license_info={"name": "Research / internal use"},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings.log_http_payloads:
        app.add_middleware(RequestResponseLoggingMiddleware)
    app.include_router(health.router)
    app.include_router(amplitude.router)
    app.include_router(quizzes.router)
    app.include_router(history.router)
    app.include_router(teacher.router)
    return app


app = create_app()
