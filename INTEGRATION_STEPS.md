# Integration Steps — Component 2

Switch from standalone local testing to live Component 1 / 3 / 4.  
Search for `PEER_HTTP_LIVE` and `LIVE INTEGRATION`.

**Inbound API prefix:** `/api/v1/assessment-engine`

## Seeded users

| user_id | role | class_code |
|---------|------|------------|
| `mock-student-unassigned` | student | — |
| `mock-student-class-a` | student | `CLASS-A` |
| `mock-teacher-1` | teacher | `CLASS-A` |

```powershell
python -m scripts.db.seed_mock_users
```

## Peer URLs (hardcoded — not `.env`)

**File:** `src/iae/config/peers.py`

```python
COMPONENT_1_URL = "http://localhost:8000"
COMPONENT_3_URL = "http://localhost:8002"
COMPONENT_4_URL = "http://localhost:8003"
PEER_HTTP_LIVE = False  # True when peers are reachable
```

Component 2 (this service) runs on **:8004** locally.

**Clients / mocks:** `src/iae/infrastructure/clients/peers.py`

## Layer map (for viva navigation)

| Layer | Path | Responsibility |
|-------|------|----------------|
| API | `src/iae/api/` | Routers, HTTP schemas, DI |
| Domain | `src/iae/domain/` | Models, catalogs, protocols |
| Application | `src/iae/application/` | Use-case services, grading |
| Adaptive | `src/iae/adaptive/` | Multivariate Elo policy |
| Infrastructure | `src/iae/infrastructure/` | Postgres, LLM, RAG, peer HTTP |

## Quick verify

```powershell
$env:PYTHONPATH = "src"
uvicorn iae.api.main:app --reload --port 8004
python -m scripts.qa.smoke_v1
python -m iae.evaluation.run_validation
```
