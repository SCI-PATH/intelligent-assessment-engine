"""Capability interfaces (Dependency Inversion).

The application layer depends only on these protocols. Concrete implementations
live in `iae.infrastructure.*` and `iae.adaptive.*` and are wired in
`iae.api.bootstrap`.
"""

from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from iae.core.models import (
    AttemptRecord,
    Chunk,
    GradeResult,
    Question,
    QuestionType,
    RlAction,
    RlState,
    SessionState,
)


@runtime_checkable
class IEmbedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class ILlmJson(Protocol):
    """LLM client constrained to return parsed JSON objects."""

    def generate_json(self, prompt: str, *, temperature: float = 0.3) -> dict: ...


@runtime_checkable
class IChunkRepository(Protocol):
    def replace_all(self, chunks: Iterable[Chunk]) -> int: ...

    def find(
        self,
        *,
        chapter_name: str | None = None,
        sub_concept: str | None = None,
        limit: int | None = None,
    ) -> list[Chunk]: ...

    def count(self) -> int: ...


@runtime_checkable
class IQuestionRepository(Protocol):
    def insert_many(self, questions: Iterable[Question]) -> int: ...

    def find_one_unused(
        self,
        *,
        chapter_name: str,
        sub_concept: str,
        dok_level: int,
        question_type: QuestionType,
        excluded_ids: list[str],
    ) -> Question | None: ...

    def count_matching(
        self,
        *,
        chapter_name: str | None = None,
        sub_concept: str | None = None,
        dok_level: int | None = None,
        question_type: QuestionType | None = None,
    ) -> int: ...

    def get(self, question_id: str) -> Question | None: ...


@runtime_checkable
class ISessionRepository(Protocol):
    def create(self, session: SessionState) -> SessionState: ...

    def get(self, session_id: str) -> SessionState | None: ...

    def update(self, session: SessionState) -> None: ...


@runtime_checkable
class IRlPolicy(Protocol):
    def cold_start_action(self, scope_chapter: str) -> RlAction: ...

    def next_action(self, state: RlState, history: list[AttemptRecord]) -> RlAction: ...


@runtime_checkable
class IGradingService(Protocol):
    def grade(self, question: Question, student_answer: str) -> GradeResult: ...

