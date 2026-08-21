# Intelligent Assessment Engine (Component 2)

Component 2 generates, banks, serves, and grades Sri Lankan science questions for grades 6-9. It runs Amplitude placement, Elo-based adaptive quizzes, teacher bank review, and talks to peer microservices:

| Peer | Role |
|------|------|
| **Component 1** (Lesson Engine) | Starts post-lesson quizzes; reads initial Amplitude category |
| **Component 3** (Engagement) | Kill-switch terminates an active quiz |
| **Component 4** (BKT / Analytics) | Owns mastery; C2 calls BKT snapshot + assessment-submit |

**Inbound API prefix:** `/api/v1/assessment-engine`  
**Local service:** `http://localhost:8001` · Swagger: `/docs`

---

## Tech stack (and why)

| Technology | Justification |
|------------|---------------|
| **FastAPI** | Typed request/response models, automatic OpenAPI for peer contracts, dependency injection for Clean Architecture wiring |
| **PostgreSQL** (`question_engine` schema) | Durable quiz history, bank, and Amplitude results on shared Neon without colliding with peer schemas |
| **ChromaDB** | Local vector store for textbook chunk RAG used during question generation |
| **Time-Discounted Elo** | Transparent DDA research module (ability rating + DOK targeting) without inventing a second BKT store |

BKT P(L) values live only in Component 4. Component 2 keeps a **session-memory** snapshot.

---

## System flow

### RAG question generation

1. Textbook PDFs are chunked and embedded into Chroma (`scripts/ingest_and_tag_chunks`).
2. Chunks are tagged with Excel Topic ID (Canonical) values from `data/skills/Skill-Heirarchies-G6-G9-Full-Chapters.xlsx`.
3. Teacher generate (or bank CLI) retrieves top-k chunks for a topic, prompts the LLM for one of four types (`MCQ`, `ShortAnswer`, `MultiBlank`, `TrueFalse`), and stores the item in `question_engine.questions`.
4. MCQ / TrueFalse generation also writes `distractor_tag` + `distractor_label` into the payload so later attempts can look them up for Component 4.

### Assessment types

1. **Amplitude Diagnostic Test** — survey + fixed **10 questions per grade** → `BASIC` | `INTERMEDIATE` | `ADVANCED`. No BKT.
2. **Customizable Quiz** — pick `chapter_ids`, count, types. Elo DDA + C4 snapshot/submit.
3. **Post-Lesson Quiz** — Component 1/3 passes `chapter_id`; length 15; same DDA loop.

### Amplitude Test

1. `POST .../amplitude/survey`
2. `GET .../amplitude/quiz?grade=` — same 10 bank IDs per grade (`amplitude_fixed_items`)
3. `POST .../amplitude/evaluate` — 60% quiz + 40% history → category on `users`
4. Component 1 reads `GET .../students/{id}/initial-category`

Local testing: inject `grade` and `user_id` before live profile wiring.

### Dynamic Difficulty Adjustment (Time-Discounted Elo)

Student ability rating `R` (seeded from C4 mastery when available, else ~1000).

```text
b = 800 + (dok - 1) * 200
expected = 1 / (1 + 10 ** ((b - R) / 400))
time_factor = clip(T / max(t, 1), 0.5, 1.5)
delta = K * time_factor * (s - expected)
R <- R + delta
```

Next DOK near the new rating, stepped by at most ±1. Types rotate MCQ → TrueFalse → MultiBlank → ShortAnswer.

**Served questions:** permanently blocked only after a **correct** answer or **similarity ≥ 0.8**. Exhaustion rotates previously mastered items instead of failing empty.

---

## Database (`question_engine`)

### Database Management Strategy

The backend uses a **non-destructive, strictly idempotent** initialization strategy (`CREATE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`). **No automated drop scripts** are included, to protect the live question bank on shared Neon. Table resets must be performed **manually** via a SQL client (DBeaver / pgAdmin).

```powershell
python -m scripts.init_postgres
python -m scripts.db.test_connection
```

### Tables (logical order)

1. **users** — Stub FK parent; opaque `user_id`, optional `grade`, Amplitude fields, `initial_category`.
2. **questions** — Bank; payload JSONB includes MCQ/TF `distractor_tag` / `distractor_label`.
3. **amplitude_fixed_items** — Exactly 10 `(grade, position)` → `question_id`; never reshuffled once set.
4. **amplitude_attempts** — Amplitude evaluate history.
5. **assessment_sessions** — Quiz run: chapters, Elo, session-memory `bkt_snapshot`, history, status.
6. **attempts** — Graded answers.
7. **served_questions** — Permanent block after success / high similarity.
8. **analytics_events** — Local copy of C4 payload.
9. **placement_evaluations** — Older placement rows (Amplitude is live).
10. **frustration_cues**, **bkt_mastery**, **past_paper_items** — Placeholders; do not write BKT here.

Shared IDs: `user_id`, Excel `topic_id`, `chapter_id` (`G6_C8` from `data/chapter_ids_g6_g9.csv`).

---

## Running the app

Use **Python 3.12** (not 3.14). On Windows, put the venv on a short path so PyTorch does not hit path-length errors.

```powershell
C:\Python312\python.exe -m venv C:\iae-venv
C:\iae-venv\Scripts\Activate.ps1
python -m pip install --no-cache-dir -r requirements.txt
# .env: DATABASE_URL + LLM keys; peer URLs in src/iae/config/peers.py

$env:PYTHONPATH = "src"
python -m scripts.db.test_connection
python -m scripts.init_postgres
python -m scripts.db.seed_mock_users
uvicorn iae.api.main:app --reload --port 8001
```

Streamlit: `streamlit run frontend_test/streamlit_app.py`  
Smoke: `python -m scripts.qa.smoke_v1`

Peer URLs are **hardcoded** in `src/iae/config/peers.py` (`http://localhost:8002|8003|8004`). Set `PEER_HTTP_LIVE = True` for live httpx; while `False`, CSV-aligned mocks are used.

---

## API and integration

### Inbound (Component 2)

| Method | Path | Caller |
|--------|------|--------|
| POST | `/api/v1/assessment-engine/amplitude/survey` | Frontend |
| GET | `/api/v1/assessment-engine/amplitude/quiz?grade=` | Frontend |
| POST | `/api/v1/assessment-engine/amplitude/evaluate` | Frontend |
| GET | `/api/v1/assessment-engine/students/{id}/initial-category` | C1 + Frontend |
| POST | `/api/v1/assessment-engine/quizzes/customizable` | Frontend |
| POST | `/api/v1/assessment-engine/quizzes/post-lesson` | C1 / C3 |
| GET | `/api/v1/assessment-engine/quizzes/{id}/next` | Frontend |
| POST | `/api/v1/assessment-engine/quizzes/{id}/answer` | Frontend |
| GET | `/api/v1/assessment-engine/quizzes/{id}/results` | Frontend |
| POST | `/api/v1/assessment-engine/quizzes/{id}/terminate` | C3 |
| GET/POST | `/api/v1/assessment-engine/students/{id}/sessions...` | Frontend |
| GET/POST | `/api/v1/assessment-engine/teacher/...` | Frontend |
| GET | `/` | Health |

### Outbound (Component 4)

1. `POST {COMPONENT_4_URL}/api/v1/quiz/bkt-snapshot` at quiz start (session memory only).
2. `POST {COMPONENT_4_URL}/api/v1/assessment-submit` after each graded answer (unified payload; unused fields `null`).

`distractor_tag` in `NEAR_MISS` | `MISCONCEPTION` | `COMPLETE_MISS`.

Docs: `docs/COMPONENT2_COMPONENT4_INTEGRATION.md`, `docs/QuestionEngine-BKT-Snapshot.md`, `docs/FRONTEND_INTEGRATION.md`, `INTEGRATION_STEPS.md`.

---

## Package layout

```text
src/iae/
  api/            FastAPI routes, schemas, bootstrap, deps
  domain/         Pydantic models, protocols, chapter/skill catalogs
  application/    Quiz, Amplitude, Teacher, History services + grading
  adaptive/       Time-Discounted Elo + multivariate next-item policy
  infrastructure/ Postgres, Chroma, LLM, peer HTTP clients + mocks
  evaluation/     Elo RMSE, grading confusion matrix, routing sanity
  config/         peers.py (hardcoded URLs), settings.py, app.yaml, topics.yaml
  prompts/        Research-grade Jinja generation + grading templates
frontend_test/    Streamlit harness
scripts/          init_postgres, seed, bank, smoke
docs/             Integration contracts
```
