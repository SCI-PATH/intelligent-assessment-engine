"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from iae.api.bootstrap import build_container
from iae.api.legacy_aliases import DEPRECATED_NOTE
from iae.api.routes import assessment, health, placement, teacher
from iae.api.v1 import amplitude as v1_amplitude
from iae.api.v1 import history as v1_history
from iae.api.v1 import quizzes as v1_quizzes
from iae.api.v1 import teacher as v1_teacher

OPENAPI_TAGS = [
    {
        "name": "Health",
        "description": "Liveness / service identity checks.",
    },
    {
        "name": "Amplitude",
        "description": (
            "**Primary initial diagnostic.** Survey → fixed 10-item quiz → "
            "`POST /api/v1/amplitude/evaluate` returns `BASIC` | `INTERMEDIATE` | `ADVANCED` "
            "(60% quiz + 40% historical composite). **No BKT.**"
        ),
    },
    {
        "name": "Quizzes",
        "description": (
            "Customizable and post-lesson sessions driven by Time-Discounted Elo DDA. "
            "**Component 4:** quiz start → `POST {C4}/api/v1/quiz/bkt-snapshot` with "
            "`chapter_ids` (`G6_C8` … from `data/chapter_ids_g6_g9.csv`); "
            "each answer → unified `POST {C4}/api/v1/assessment-submit` "
            "(optional `chapter_ids` on multi-chapter quizzes). "
            "BKT stays in session memory only. "
            "Kill switch: `POST /api/v1/quiz/{session_id}/terminate`."
        ),
    },
    {
        "name": "Student History",
        "description": "Session list/detail plus optional LLM analysis of wrong answers.",
    },
    {
        "name": "Placement",
        "description": (
            "**Deprecated** legacy placement (`WEAK` | `AVERAGE` | `ADVANCED`). "
            f"{DEPRECATED_NOTE}"
        ),
    },
    {
        "name": "Diagnostic Assessment",
        "description": (
            "**Deprecated** chapter diagnostic under `/assessment/sessions/*`. "
            "Prefer `/api/v1/quizzes/...`."
        ),
    },
    {
        "name": "Teacher Hub",
        "description": (
            "Question-bank tools under `/api/v1/teacher` (and legacy `/teacher`). "
            "Reject with enum reasons; `FACTUAL_ERROR` triggers LLM confirmation."
        ),
    },
]

API_DESCRIPTION = """
Intelligent Assessment Engine (Component 2) HTTP API for Sri Lankan science grades 6–9.

## Preferred contract: `/api/v1`

| Consumer | Endpoint | What you get |
|----------|----------|--------------|
| Frontend | `POST /api/v1/amplitude/evaluate` | `category`: `BASIC` \\| `INTERMEDIATE` \\| `ADVANCED` |
| Frontend | `/api/v1/quizzes/*` | Customizable DDA quiz + C4 analytics submit |
| Component 1 | `POST /api/v1/quiz/trigger-post-lesson` | 15-question chapter quiz session |
| Component 3 | `POST /api/v1/quiz/{session_id}/terminate` | Kill-switch end session |
| Component 4 | inbound via C2 client | unified assessment-submit payload |
| Student UI | `/api/v1/student/{id}/sessions*` | history + LLM analyze |
| Teacher UI | `/api/v1/teacher/*` | bank CRUD + rejection reasons |

Legacy `/assessment/*` and `/teacher/*` paths remain as thin compatibility aliases.

## Quick start
1. **Amplitude** — survey → quiz → evaluate → read `initial-category`.
2. **Customizable quiz** — create → loop `next` / `answer` until complete.
3. **Teacher Hub** — generate / approve / reject with reasons.

## Notes
- **Base URL (local):** `http://localhost:8001`
- **Auth:** none (research phase). CORS allows all origins.
- Interactive docs: [`/docs`](/docs) · [`/redoc`](/redoc)
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.container = build_container()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Intelligent Assessment Engine",
        version="0.2.0",
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
    # Preferred /api/v1 surface
    app.include_router(v1_amplitude.router)
    app.include_router(v1_quizzes.router)
    app.include_router(v1_history.router)
    app.include_router(v1_teacher.router)
    # Deprecated compatibility aliases
    app.include_router(assessment.router)
    app.include_router(placement.router)
    app.include_router(teacher.router)
    return app


app = create_app()
