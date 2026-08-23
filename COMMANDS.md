# Commands — Intelligent Assessment Engine (Component 2)

PowerShell from the repo root. Inbound API prefix: `/api/v1/assessment-engine`.

Venv is already at `C:\iae-venv` (Python 3.12). `.env` already has `DATABASE_URL` (Neon). Schema `question_engine` must already exist — the app **never** creates it; it only creates tables inside that schema.

---

## 1. Activate (every new terminal)

```powershell
cd "c:\Users\yenul\Documents\Research Project\intelligent-assessment-engine"
C:\iae-venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
```

## 2. Create tables + seed users (inside existing `question_engine`)

```powershell
python -m scripts.db.test_connection
python -m scripts.init_postgres
python -m scripts.db.seed_mock_users
```

Expect `OK` / tables listed — not `CREATE SCHEMA` errors.

## 3. Skills catalog + RAG ingest (all grades 6–9)

PDFs are under `data/`. Run once (or again after curriculum/PDF changes):

```powershell
python -m scripts.sync_skill_catalog

foreach ($g in 6,7,8,9) {
  Write-Host "=== ingest grade $g ==="
  python -m scripts.ingest_and_tag_chunks --grade $g
}
```

## 4. Generate question bank (all grades)

Uses LLM (`LLM_PROVIDER` / keys in `.env`). **Slow** (many OpenAI calls; ~10–60s each).
Chroma lines like `Failed to send telemetry event...` are harmless — ignore them.

Ingest (step 3) is already done if you saw “Wrote N chunks to Chroma” for grades 6–9.
Resume generation only (no need to re-ingest):

```powershell
# Start with one grade to confirm the API key works, then run the rest
python -m scripts.generate_bank --grade 6

foreach ($g in 7,8,9) {
  Write-Host "=== generate bank grade $g ==="
  python -m scripts.generate_bank --grade $g
}
```

You should see lines like `generating dok=1 type=mcq ...` then `ok`. If it hangs with no progress for >90s, the OpenAI call times out and retries.

## 4b. Generate Amplitude placement bank (exactly 10 MCQ/TF per grade)

Separate from the adaptive bank. Writes to `question_engine.amplitude_questions` with `status=approved`.

```powershell
python -m scripts.generate_amplitude_bank
# or one grade:
python -m scripts.generate_amplitude_bank --grade 7
# regenerate:
python -m scripts.generate_amplitude_bank --grade 6 --force
```

Verify scoring / evaluate:

```powershell
python -m scripts.qa.test_amplitude_scoring
python -m scripts.qa.test_amplitude_evaluate
```

## 5. Start API

```powershell
uvicorn iae.api.main:app --reload --port 8001
```

Swagger: http://localhost:8001/docs

## 6. Smoke + validation (second terminal)

```powershell
cd "c:\Users\yenul\Documents\Research Project\intelligent-assessment-engine"
C:\iae-venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"

python -m scripts.qa.smoke_all_endpoints
python -m scripts.qa.smoke_v1
python -m iae.evaluation.run_validation
```

`smoke_all_endpoints` hits every Swagger inbound route (Amplitude, quizzes, history, teacher). Or exercise endpoints manually in Swagger under `/api/v1/assessment-engine` — request bodies are pre-filled with editable examples.

## Streamlit (optional)

```powershell
$env:API_BASE_URL = "http://localhost:8001"
streamlit run frontend_test/streamlit_app.py
```

---

## Setup (one-time only — already done)

Do **not** re-run unless you deleted `C:\iae-venv`.

```powershell
C:\Python312\python.exe -m venv C:\iae-venv
C:\iae-venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --no-cache-dir -r requirements.txt
```

Neon admin (not the app role): create schema once via `scripts/neon_schema_init.sql` or console, then grant the app user rights **inside** `question_engine` only.
