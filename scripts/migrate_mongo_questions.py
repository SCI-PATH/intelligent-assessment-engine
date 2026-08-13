"""Copy existing Mongo ``questions`` into Postgres as ``approved`` rows.

Safe to re-run: existing UUIDs that are already in Postgres are skipped.
"""

from __future__ import annotations

import sys
from uuid import UUID

from iae.core.models import Question, QuestionOrigin, QuestionStatus
from iae.infrastructure.mongo.client import get_database
from iae.infrastructure.postgres.engine import get_session_factory, init_schema
from iae.infrastructure.postgres.questions_repo import PostgresQuestionRepository


def main() -> int:
    init_schema()
    repo = PostgresQuestionRepository(get_session_factory())
    mongo = get_database()["questions"]
    inserted = 0
    skipped = 0
    failed = 0
    batch: list[Question] = []
    for doc in mongo.find({}):
        doc.setdefault("status", QuestionStatus.APPROVED.value)
        doc.setdefault("origin", QuestionOrigin.AI.value)
        if "_id" in doc and "id" not in doc:
            doc["id"] = doc["_id"]
        try:
            UUID(str(doc.get("id") or doc.get("_id")))
            question = Question(**doc)
            question.status = QuestionStatus.APPROVED
            if repo.get(question.id) is not None:
                skipped += 1
                continue
            batch.append(question)
        except Exception as exc:
            failed += 1
            print(f"  skip invalid mongo doc: {exc}", file=sys.stderr)
            continue
        if len(batch) >= 50:
            inserted += repo.insert_many(batch)
            batch.clear()
    if batch:
        inserted += repo.insert_many(batch)
    print(f"Migrated {inserted} questions ({skipped} already present, {failed} invalid).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
