"""``ISessionRepository`` backed by MongoDB."""

from __future__ import annotations

from datetime import datetime, timezone

from pymongo.database import Database

from iae.core.models import SessionState

_COLLECTION = "sessions"


class MongoSessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, session: SessionState) -> SessionState:
        self._db[_COLLECTION].insert_one(session.model_dump(by_alias=True))
        return session

    def get(self, session_id: str) -> SessionState | None:
        doc = self._db[_COLLECTION].find_one({"_id": session_id})
        return SessionState(**doc) if doc else None

    def update(self, session: SessionState) -> None:
        session.updated_at = datetime.now(timezone.utc)
        self._db[_COLLECTION].replace_one(
            {"_id": session.session_id},
            session.model_dump(by_alias=True),
        )
