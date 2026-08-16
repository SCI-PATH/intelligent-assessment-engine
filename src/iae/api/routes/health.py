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
    description="Returns service liveness. Useful for load balancers and smoke tests.",
    responses={200: {"description": "Service is up."}},
)
def health_check() -> HealthResponse:
    """Return service liveness for smoke tests and load balancers."""
    return HealthResponse(status="ok", service="intelligent-assessment-engine")
