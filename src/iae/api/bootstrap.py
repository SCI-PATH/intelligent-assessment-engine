"""Composition root — wires infrastructure into application services."""

from __future__ import annotations

from dataclasses import dataclass

from iae.application.amplitude_service import AmplitudeService
from iae.application.grading import GradingService
from iae.application.history_service import HistoryService
from iae.application.quiz_service import QuizService
from iae.application.teacher_service import TeacherService
from iae.config.settings import get_config, get_settings
from iae.domain.protocols import IGradingService, IQuestionRepository, ISessionRepository
from iae.infrastructure.clients import Component1Client, Component3Client, Component4Client
from iae.infrastructure.llm.factory import build_json_llm, build_teacher_generator_llm
from iae.infrastructure.postgres.amplitude_repo import PostgresAmplitudeRepository
from iae.infrastructure.postgres.analytics_repo import PostgresAnalyticsRepository
from iae.infrastructure.postgres.engine import get_session_factory
from iae.infrastructure.postgres.questions_repo import PostgresQuestionRepository
from iae.infrastructure.postgres.sessions_repo import PostgresSessionRepository
from iae.infrastructure.rag.chroma_store import ChromaChunkStore
from iae.infrastructure.rag.embeddings import HuggingFaceEmbedder


@dataclass
class Container:
    sessions_repo: ISessionRepository
    questions_repo: IQuestionRepository
    grading: IGradingService
    teacher_service: TeacherService
    amplitude_service: AmplitudeService
    quiz_service: QuizService
    history_service: HistoryService
    c1: Component1Client
    c3: Component3Client
    c4: Component4Client


def build_container() -> Container:
    settings = get_settings()
    config = get_config()

    # Schema/tables are managed in Neon already — do not re-run schema.sql on boot
    # (CREATE SCHEMA needs privileges the app role may not have).
    # Manual apply if needed: python -m scripts.init_postgres
    session_factory = get_session_factory()
    questions_repo = PostgresQuestionRepository(session_factory)
    analytics_repo = PostgresAnalyticsRepository(session_factory)
    sessions_repo = PostgresSessionRepository(session_factory)
    amplitude_repo = PostgresAmplitudeRepository(session_factory)

    llm = build_json_llm(timeout_s=config.groq_grader_timeout_s)
    generator_llm = build_teacher_generator_llm()
    embedder = HuggingFaceEmbedder(config.embedding_model)
    grading = GradingService(llm=llm, embedder=embedder)
    c1 = Component1Client()
    c3 = Component3Client()
    c4 = Component4Client()

    teacher_service = TeacherService(
        questions=questions_repo,
        llm=generator_llm,
        store=ChromaChunkStore(settings.chroma_persist_dir),
        embedder=embedder,
        retrieval_top_k=config.retrieval_top_k,
        generation_max_retries=config.generation_max_retries,
        users=amplitude_repo,
        analytics=analytics_repo,
    )
    amplitude_service = AmplitudeService(
        store=amplitude_repo,
        grading=grading,
    )
    quiz_service = QuizService(
        sessions=sessions_repo,
        questions=questions_repo,
        grading=grading,
        analytics=analytics_repo,
        embedder=embedder,
        analytics_llm=llm,
        c4=c4,
        c1=c1,
        c3=c3,
    )
    history_service = HistoryService(
        sessions=sessions_repo,
        questions=questions_repo,
        llm=llm,
    )
    return Container(
        sessions_repo=sessions_repo,
        questions_repo=questions_repo,
        grading=grading,
        teacher_service=teacher_service,
        amplitude_service=amplitude_service,
        quiz_service=quiz_service,
        history_service=history_service,
        c1=c1,
        c3=c3,
        c4=c4,
    )
