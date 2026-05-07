from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "intelligent-assessment-engine"}
