"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from iae.api.bootstrap import build_container
from iae.api.routes import assessment, health, placement, teacher

OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Liveness / service identity checks.",
    },
    {
        "name": "placement",
        "description": (
            "Initial student placement: survey, 10-item diagnostic quiz, "
            "and weighted WEAK / AVERAGE / ADVANCED category."
        ),
    },
    {
        "name": "assessment",
        "description": (
            "Adaptive diagnostic sessions: create a session, fetch the next "
            "question, submit an answer for grading, and read final results. "
            "Grading is `POST /assessment/sessions/{session_id}/answer` "
            "(there is no `/submit` endpoint)."
        ),
    },
    {
        "name": "teacher",
        "description": (
            "Teacher question-bank tools: list Excel Topic IDs, generate "
            "pending items from Chroma RAG, approve/reject, and add custom "
            "questions. No auth in this research phase."
        ),
    },
]

API_DESCRIPTION = """
Intelligent Assessment Engine (IAE) HTTP API for Sri Lankan science grades 6–9.

## Quick start
1. **Placement** — survey → quiz → evaluate → store category on the student profile.
2. **Diagnostic** — create session → loop `next` / `answer` until `is_complete`.
3. **Teacher** — generate or upload bank items; only `approved` items are served to students.

## Notes
- **Base URL (local):** `http://localhost:8001`
- **Auth:** none (research phase). CORS allows all origins.
- **Pass mark:** `is_correct` when `accuracy_score >= 0.8`
- **Session length:** `max_questions` from config (default **5**)
- Interactive docs: [`/docs`](/docs) (Swagger UI) · [`/redoc`](/redoc)
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.container = build_container()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Intelligent Assessment Engine",
        version="0.1.0",
        description=API_DESCRIPTION,
        lifespan=lifespan,
        openapi_tags=OPENAPI_TAGS,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "IAE Research Project"},
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
    app.include_router(assessment.router)
    app.include_router(placement.router)
    app.include_router(teacher.router)
    return app


app = create_app()
