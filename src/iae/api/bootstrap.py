"""Composition root.

The single place that knows how to wire concrete adapters together. Routers
import a typed ``Container`` instance and depend only on its protocol fields.
"""

from __future__ import annotations

from dataclasses import dataclass

from iae.application.grading import GradingService
from iae.application.sessions import SessionLimits, SessionService
from iae.core.protocols import (
    IGradingService,
    IQuestionRepository,
    IRlPolicy,
    ISessionRepository,
)
from iae.core.settings import get_config, get_settings
from iae.infrastructure.llm.factory import build_json_llm
from iae.infrastructure.mongo.client import ensure_indexes, get_database
from iae.infrastructure.mongo.questions_repo import MongoQuestionRepository
from iae.infrastructure.mongo.sessions_repo import MongoSessionRepository
from iae.adaptive.policy import ConceptAwareNavigationPolicy, PolicyConfig


@dataclass
class Container:
    sessions_repo: ISessionRepository
    questions_repo: IQuestionRepository
    grading: IGradingService
    policy: IRlPolicy
    session_service: SessionService


def build_container() -> Container:
    settings = get_settings()
    config = get_config()
    db = get_database()
    ensure_indexes(db)

    sessions_repo = MongoSessionRepository(db)
    questions_repo = MongoQuestionRepository(db)

    llm = build_json_llm(model=config.llm_grader_model)
    grading = GradingService(llm=llm)
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
    )
    return Container(
        sessions_repo=sessions_repo,
        questions_repo=questions_repo,
        grading=grading,
        policy=policy,
        session_service=session_service,
    )


