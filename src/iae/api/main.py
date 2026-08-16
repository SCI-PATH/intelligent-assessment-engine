"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from iae.api.bootstrap import build_container
from iae.api.routes import assessment, health, placement, teacher

OPENAPI_TAGS = [
    {
        "name": "Health",
        "description": "Liveness / service identity checks.",
    },
    {
        "name": "Placement",
        "description": (
            "**Cross-component integration point.** Survey → 10-item quiz → "
            "`POST /assessment/placement/evaluate` returns student classification "
            "`WEAK` | `AVERAGE` | `ADVANCED` plus `weighted_score`, `quiz_score`, and `past_score` "
            "(70% quiz + 30% past marks)."
        ),
    },
    {
        "name": "Diagnostic Assessment",
        "description": (
            "Adaptive diagnostic sessions: create → `next` → `answer` → `results`. "
            "**Component 4 / BKT Analytics:** every "
            "`POST /assessment/sessions/{session_id}/answer` builds and persists an "
            "analytics event with `user_id`, `topic_id`, `is_correct`, `question_id`, "
            "`question_type`, `similarity_score`, `distractor_tag` "
            "(`NEAR_MISS` | `MISCONCEPTION` | `COMPLETE_MISS` for wrong MCQs), and "
            "`distractor_label`."
        ),
    },
    {
        "name": "Teacher Hub",
        "description": (
            "Question-bank tools: list Excel Topic IDs, generate pending items from "
            "Chroma RAG, approve/reject, and add custom questions. No auth in this "
            "research phase."
        ),
    },
]

API_DESCRIPTION = """
Intelligent Assessment Engine (IAE) HTTP API for Sri Lankan science grades 6–9.

## Team integration day — critical contracts

| Consumer | Endpoint | What you get |
|----------|----------|--------------|
| Frontend / recommender | `POST /assessment/placement/evaluate` | `category`: `WEAK` \\| `AVERAGE` \\| `ADVANCED`, plus `weighted_score`, `quiz_score`, `past_score` |
| Component 4 (BKT Analytics) | `POST /assessment/sessions/{session_id}/answer` | Graded attempt **and** a row in `question_engine.analytics_events` with distractor tags / similarity |

## Quick start
1. **Placement** — survey → quiz → evaluate → store category on the student profile.
2. **Diagnostic** — create session → loop `next` / `answer` until `is_complete`.
3. **Teacher Hub** — generate or upload bank items; only `approved` items are served to students.

## Stability for frontend
Public path URLs and JSON field names are the integration contract. Internal Postgres /
Chroma logic may change without breaking these routes. Sync types from
[`/openapi.json`](/openapi.json).

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
        contact={"name": "IAE Research Project — Component 3"},
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
