"""FastAPI application factory — Intelligent Assessment Engine (Component 2)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from iae.api.bootstrap import build_container
from iae.api.routes import amplitude, health, history, quizzes, teacher

OPENAPI_TAGS = [
    {"name": "Health", "description": "Liveness probe."},
    {
        "name": "Amplitude Diagnostic Test",
        "description": "Survey + fixed 10-item quiz → BASIC | INTERMEDIATE | ADVANCED.",
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

Peer URLs are hardcoded in `src/iae/config/peers.py` (`localhost:8002|8003|8004`).
Set `PEER_HTTP_LIVE = True` for live httpx.

**Base URL (local):** `http://localhost:8001` · Docs: [`/docs`](/docs)
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.container = build_container()
    yield


def create_app() -> FastAPI:
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
    app.include_router(health.router)
    app.include_router(amplitude.router)
    app.include_router(quizzes.router)
    app.include_router(history.router)
    app.include_router(teacher.router)
    return app


app = create_app()
