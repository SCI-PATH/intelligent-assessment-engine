# frontend_test (Streamlit harness)

Local visual tester for Component 2 against `/api/v1/assessment-engine`.

```powershell
# Terminal 1 — API
$env:PYTHONPATH = "src"
uvicorn iae.api.main:app --reload --port 8001

# Terminal 2 — Streamlit
$env:API_BASE_URL = "http://localhost:8001"
streamlit run frontend_test/streamlit_app.py
```

Seed users first: `python -m scripts.db.seed_mock_users`

Pages: Amplitude, Customizable Quiz, Post-lesson, History, Teacher dashboard.
