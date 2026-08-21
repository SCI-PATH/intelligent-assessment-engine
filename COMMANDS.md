# Commands — Intelligent Assessment Engine (Component 2)

PowerShell from the repo root. Inbound API prefix: `/api/v1/assessment-engine`.

## Setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Edit .env: GROQ_API_KEY, DATABASE_URL
# Peer URLs: edit src/iae/config/peers.py (not .env)
$env:PYTHONPATH = "src"
```

## Database

```powershell
python -m scripts.db.test_connection
python -m scripts.init_postgres
python -m scripts.db.seed_mock_users
```

## Run API

```powershell
$env:PYTHONPATH = "src"
uvicorn iae.api.main:app --reload --port 8001
```

- Swagger: http://localhost:8001/docs

## Smoke + algorithm validation

```powershell
$env:PYTHONPATH = "src"
python -m scripts.qa.smoke_v1
python -m iae.evaluation.run_validation
```

## Streamlit (optional)

```powershell
$env:API_BASE_URL = "http://localhost:8001"
streamlit run frontend_test/streamlit_app.py
```

## Bank / RAG (optional)

```powershell
python -m scripts.sync_skill_catalog
python -m scripts.ingest_and_tag_chunks --grade 6
python -m scripts.generate_bank --grade 6
```
