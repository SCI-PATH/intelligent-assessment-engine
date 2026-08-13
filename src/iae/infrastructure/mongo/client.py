"""MongoDB Atlas connection plumbing (sessions only until Phase 5)."""

from __future__ import annotations

from functools import lru_cache

from pymongo import MongoClient
from pymongo.database import Database

from iae.core.settings import get_settings


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise RuntimeError(
            "MONGODB_URI is not set. Add it to .env (the Atlas driver connection string)."
        )
    return MongoClient(settings.mongodb_uri, appname="iae")


def get_database() -> Database:
    return get_mongo_client()[get_settings().mongodb_db_name]


def ensure_indexes(db: Database) -> None:
    """Create the indexes the remaining Mongo session store relies on."""

    try:
        db["sessions"].drop_index("session_id_1")
    except Exception:
        pass
    db["sessions"].create_index([("updated_at", -1)], name="sessions_updated_at")
