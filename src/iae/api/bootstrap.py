"""Composition root.

The single place that knows how to wire concrete adapters together. Routers
import a typed ``Container`` instance and depend only on its protocol fields.
"""

from __future__ import annotations

from dataclasses import dataclass

from iae.adaptive.policy import ConceptAwareNavigationPolicy, PolicyConfig
from iae.application.grading import GradingService
from iae.application.placement import PlacementService
from iae.application.sessions import SessionLimits, SessionService
from iae.application.teacher import TeacherService
from iae.core.protocols import (
    IGradingService,
    IQuestionRepository,
    IRlPolicy,
    ISessionRepository,
)
from iae.core.settings import get_config, get_settings
from iae.infrastructure.llm.factory import build_json_llm
from iae.infrastructure.postgres.analytics_repo import PostgresAnalyticsRepository
from iae.infrastructure.postgres.engine import get_session_factory, init_schema
from iae.infrastructure.postgres.questions_repo import PostgresQuestionRepository
from iae.infrastructure.postgres.placement_repo import PostgresPlacementRepository
from iae.infrastructure.postgres.sessions_repo import PostgresSessionRepository
from iae.infrastructure.rag.chroma_store import ChromaChunkStore
from iae.infrastructure.rag.embeddings import HuggingFaceEmbedder


@dataclass
class Container:
    sessions_repo: ISessionRepository
    questions_repo: IQuestionRepository
    grading: IGradingService
    policy: IRlPolicy
    session_service: SessionService
    teacher_service: TeacherService
    placement_service: PlacementService


def build_container() -> Container:
    settings = get_settings()
    config = get_config()

    init_schema()
    session_factory = get_session_factory()
    questions_repo = PostgresQuestionRepository(session_factory)
    analytics_repo = PostgresAnalyticsRepository(session_factory)
    sessions_repo = PostgresSessionRepository(session_factory)
    placement_repo = PostgresPlacementRepository(session_factory)

    llm = build_json_llm(model=config.llm_grader_model)
    generator_llm = build_json_llm(model=config.llm_model)
    embedder = HuggingFaceEmbedder(config.embedding_model)
    grading = GradingService(llm=llm, embedder=embedder)
    policy = ConceptAwareNavigationPolicy(
        PolicyConfig(
            cold_start_dok=config.cold_start_dok,
            rolling_window=config.rolling_window,
            target_accuracy_lower=config.target_accuracy_lower,
            target_accuracy_upper=config.target_accuracy_upper,
        )
    )
    session_service = SessionService(
        sessions=sessions_repo,
        questions=questions_repo,
        grading=grading,
        policy=policy,
        limits=SessionLimits(
            max_questions=config.max_questions,
            rolling_window=config.rolling_window,
            response_time_target_seconds=config.response_time_target_seconds,
        ),
        analytics=analytics_repo,
        embedder=embedder,
        analytics_llm=llm,
    )
    teacher_service = TeacherService(
        questions=questions_repo,
        llm=generator_llm,
        store=ChromaChunkStore(settings.chroma_persist_dir),
        embedder=embedder,
        retrieval_top_k=config.retrieval_top_k,
        generation_max_retries=config.generation_max_retries,
    )
    placement_service = PlacementService(store=placement_repo, questions=questions_repo)
    return Container(
        sessions_repo=sessions_repo,
        questions_repo=questions_repo,
        grading=grading,
        policy=policy,
        session_service=session_service,
        teacher_service=teacher_service,
        placement_service=placement_service,
    )
