from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    service: str = Field(examples=["intelligent-assessment-engine"])


@router.get(
    "/",
    response_model=HealthResponse,
    summary="Health check",
    description=(
        "**Purpose:** Liveness probe for load balancers, Docker HEALTHCHECK, and smoke tests.\n\n"
        "**Peer services:** none.\n\n"
        "**Response:** `{ \"status\": \"ok\", \"service\": \"intelligent-assessment-engine\" }`.\n\n"
        "**How to Test:** Open `/docs` → Execute this endpoint → expect 200. "
        "Or browser: `http://127.0.0.1:8004/`."
    ),
    responses={200: {"description": "Service is up."}},
)
def health_check() -> HealthResponse:
    """Return service liveness for smoke tests and load balancers."""
    return HealthResponse(status="ok", service="intelligent-assessment-engine")
