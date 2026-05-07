"""MongoDB Atlas connection plumbing.

A single ``MongoClient`` instance per process is sufficient for our scale; the
driver multiplexes server selection internally. Tests can swap in any other
``Database`` that satisfies the repository protocols.
"""

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
    """Create the indexes the application relies on. Idempotent."""

    db["chunks"].create_index([("chapter_name", 1), ("sub_concept", 1)])
    db["questions"].create_index(
        [
            ("chapter_name", 1),
            ("sub_concept", 1),
            ("dok_level", 1),
            ("question_type", 1),
        ],
        name="bank_lookup",
    )
    # Legacy fix: early versions created a unique index on `session_id`, but
    # session docs use `_id` as the canonical identifier. That old index causes
    # duplicate-key errors on new sessions (`session_id: null`).
    try:
        db["sessions"].drop_index("session_id_1")
    except Exception:
        pass

    # `_id` is already unique by Mongo default; keep one helpful secondary index.
    db["sessions"].create_index([("updated_at", -1)], name="sessions_updated_at")
