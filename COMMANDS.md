# Commands — Intelligent Assessment Engine (Component 2)

All commands assume PowerShell from the repo root.

## 1) Virtual environment & install

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Edit .env: set GROQ_API_KEY and DATABASE_URL
$env:PYTHONPATH = "src"
```

## 2) Database URL — local vs Neon (`question_engine` only)

**Local:**

```env
DATABASE_URL=postgresql+psycopg://iae:iae@localhost:5432/iae
```

**Neon (`neondb`):**

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@ep-xxxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
```

## 3) Test connection

```powershell
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m scripts.db.test_connection
```

## 4) Init schema + seed mock users

```powershell
python -m scripts.init_postgres
python -m scripts.db.seed_mock_users
```

Optional Neon SQL Editor: `scripts/neon_schema_init.sql`

## 5) Question bank / RAG pipeline

```powershell
python -m scripts.sync_skill_catalog
python -m scripts.extract_subconcepts --grade 6
python -m scripts.ingest_and_tag_chunks --grade 6
python -m scripts.generate_bank --grade 6
```

## 6) Run FastAPI (Swagger)

```powershell
$env:PYTHONPATH = "src"
uvicorn iae.api.main:app --reload --port 8001
```

- Swagger: http://localhost:8001/docs  
- OpenAPI: http://localhost:8001/openapi.json  

## 7) Streamlit harness

```powershell
$env:API_BASE_URL = "http://localhost:8001"
streamlit run frontend_test/streamlit_app.py
```

## 8) Smoke / QA

```powershell
$env:PYTHONPATH = "src"
python -m scripts.qa.smoke_v1
```

## Docs (all under `docs/`)

- `docs/FRONTEND_INTEGRATION.md`
- `docs/COMPONENT2_COMPONENT4_INTEGRATION.md`
- `docs/QuestionEngine-BKT-Snapshot.md`
- `docs/QuestionEngine-Integration.md`
- `data/chapter_ids_g6_g9.csv`
