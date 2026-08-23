# Component 2 — Intelligent Assessment Engine (FastAPI / question_engine).
# Python 3.12 slim (torch / sentence-transformers / chromadb need glibc wheels).
FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    HOST=0.0.0.0 \
    PORT=8004 \
    CHROMA_PERSIST_DIR=/app/data/chroma_db

# System deps for psycopg / some scientific wheels
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
COPY src ./src
COPY data/chapter_ids_g6_g9.csv ./data/chapter_ids_g6_g9.csv
COPY data/skills/.gitkeep ./data/skills/
COPY scripts/neon_schema_init.sql ./scripts/neon_schema_init.sql
COPY scripts/ingest_and_tag_chunks.py ./scripts/ingest_and_tag_chunks.py

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir . \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /root/.cache/pip

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /app/data/chroma_db /app/data/cache \
    && chown -R app:app /app

USER app

EXPOSE 8004

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8004/', timeout=4)"

CMD ["uvicorn", "iae.api.main:app", "--host", "0.0.0.0", "--port", "8004"]
