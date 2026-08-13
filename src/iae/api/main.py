"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from iae.api.bootstrap import build_container
from iae.api.routes import assessment, health, teacher


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.container = build_container()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Intelligent Assessment Engine",
        version="0.1.0",
        lifespan=lifespan,
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
    app.include_router(teacher.router)
    return app


app = create_app()
