# Intelligent Assessment Engine — Commands

Everyday terminal commands for local development and team integration day.
Run all of these from the **repo root** unless noted.

## 1. Activate the virtualenv (Windows PowerShell)

```powershell
cd "C:\Users\yenul\Documents\Research Project\intelligent-assessment-engine"
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks scripts:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

## 2. Start the backend (hot-reload, port 8001)

```powershell
$env:PYTHONPATH = "src"
uvicorn iae.api.main:app --reload --host 0.0.0.0 --port 8001
```

- Swagger UI: http://localhost:8001/docs  
- ReDoc: http://localhost:8001/redoc  
- OpenAPI JSON: http://localhost:8001/openapi.json  
- Health: http://localhost:8001/

## 3. Database schema init / migrations

### Local Postgres (`.env` → `DATABASE_URL`)

```powershell
python -m scripts.init_postgres
```

### Shared Neon instance (SQL Editor or `psql`)

Paste / run the idempotent script:

```text
scripts/neon_schema_init.sql
```

```powershell
# If you have psql and DATABASE_URL pointing at Neon:
psql $env:DATABASE_URL -f scripts/neon_schema_init.sql
```

Creates schema `question_engine` plus tables:
`users`, `questions`, `assessment_sessions`, `served_questions`, `attempts`,
`analytics_events`, `placement_evaluations`, and placeholders
`frustration_cues`, `bkt_mastery`, `past_paper_items`.

## 4. Sync Excel Topic ID catalog

```powershell
python -m scripts.sync_skill_catalog
```

Writes `src/iae/config/topics.yaml` from the skill-hierarchy Excel file.

## 5. Ingest textbook PDFs into ChromaDB (grades 6–9)

Requires `subconcepts.yaml` for the grade (extract first if missing).

```powershell
# Optional: extract / refresh sub-concepts (LLM)
python -m scripts.extract_subconcepts --grade 6
python -m scripts.extract_subconcepts --grade 7
python -m scripts.extract_subconcepts --grade 8
python -m scripts.extract_subconcepts --grade 9

# Embed + tag chunks into data/chroma_db
python -m scripts.ingest_and_tag_chunks --grade 6
python -m scripts.ingest_and_tag_chunks --grade 7
python -m scripts.ingest_and_tag_chunks --grade 8
python -m scripts.ingest_and_tag_chunks --grade 9
```

G7–G9 pull both PDF parts automatically via `curriculum.yaml` `pdf_id`s.

## 6. Seed / generate question bank

There is **no** `--count` flag on the bank script. Use `--chapter` and/or `--per-combo`
for a small sample:

```powershell
# Small sample: one chapter, 1 question per (DOK × type) combo
python -m scripts.generate_bank --grade 6 --chapter Magnets --per-combo 1

# Alias entrypoint (same as generate_bank)
python -m scripts.generate_question_bank --grade 6 --chapter Magnets --per-combo 1

# Full grade rebuild (expensive — many LLM calls)
python -m scripts.generate_bank --grade 6
python -m scripts.generate_bank --grade 7
python -m scripts.generate_bank --grade 8
python -m scripts.generate_bank --grade 9
```

Items from this script are stored as **`approved`** so placement/diagnostic can serve them immediately.

## 7. Run the automated E2E suite

With Postgres + Chroma + bank available and `DATABASE_URL` / `GROQ_API_KEY` in `.env`:

```powershell
python -m scripts.test_engine_e2e
```

Covers placement survey/quiz/evaluate, teacher approve path, and all four graders
(including analytics payload persistence).

---

## Frontend integration & API stability

### Connecting Next.js

In the frontend `.env.local` (or equivalent):

```env
NEXT_PUBLIC_IAE_API_BASE=http://localhost:8001
```

All client `fetch` / axios calls should prefix with that base (see
`FRONTEND_INTEGRATION_GUIDE.md`). CORS on this backend is open (`*`) for the
research phase.

### Keeping TypeScript types in sync

1. Start the API on port **8001**.
2. Open **Swagger UI** at http://localhost:8001/docs to explore and Try-it-out.
3. Download the live contract: http://localhost:8001/openapi.json  
   Generate or hand-sync TS types from that file (or copy the types already
   documented in `FRONTEND_INTEGRATION_GUIDE.md`).

### Immutable public URLs

During team integration, treat these paths and JSON field names as **stable**:

| Area | Stable endpoints |
|------|------------------|
| Placement | `POST /assessment/placement/survey`, `GET /assessment/placement/quiz`, `POST /assessment/placement/evaluate` |
| Diagnostic | `POST /assessment/sessions`, `POST /assessment/sessions/{id}/next`, `POST /assessment/sessions/{id}/answer`, `GET /assessment/sessions/{id}/results` |
| Teacher | `/teacher/topics`, `/teacher/generate`, `/teacher/questions`, approve/reject |

Internal DB columns, Chroma layout, or grading heuristics may change without
renaming these URLs. Prefer consuming OpenAPI field names rather than scraping
HTML or hard-coding internal table shapes.

### Integration contracts (Component 4 + Frontend)

1. **`POST /assessment/placement/evaluate`** → `category` is exactly
   `WEAK` | `AVERAGE` | `ADVANCED`, with `weighted_score`, `quiz_score`, `past_score`.
2. **Component 4 ingest** — after grading, Component 2 POSTs the unified analytics
   JSON to Component 4’s endpoint:
   `POST {ANALYTICS_BASE_URL}/api/v1/assessment-submit`
   (set `ANALYTICS_BASE_URL=http://127.0.0.1:8000` in `.env`).
   Full per-type request bodies: [`COMPONENT2_COMPONENT4_INTEGRATION.md`](./COMPONENT2_COMPONENT4_INTEGRATION.md).
