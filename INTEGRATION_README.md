# Integration README — Component 2 (Intelligent Assessment Engine)

**Audience:** Frontend, Component 1 (Lesson Engine), Component 3 (Engagement), Component 4 (Learner Analytics).  
**This file is the team handshake source of truth for calling Component 2.**

| | |
|--|--|
| **Local base URL** | `http://localhost:8004` |
| **API prefix** | `/api/v1/assessment-engine` |
| **OpenAPI** | `http://localhost:8004/docs` |
| **Headers** | `Content-Type: application/json` · `Accept: application/json` |
| **Auth** | none (research phase) |

Peer microservice hosts are **hardcoded** in [`src/iae/config/peers.py`](src/iae/config/peers.py) (`COMPONENT_1_URL`, `COMPONENT_3_URL`, `COMPONENT_4_URL`, `PEER_HTTP_LIVE`). Do **not** put peer URLs in `.env`.

---

## 1) Aptitude placement (pre-use / post-registration)

Runs **before** lessons and adaptive quizzes. Categories: **`BASIC` | `INTERMEDIATE` | `ADVANCED`** (no BKT).

Scoring: **60%** fixed 10-item quiz + **40%** survey/history composite.

| Step | Method | Path |
|------|--------|------|
| List chapters for multi-select | `GET` | `/api/v1/assessment-engine/amplitude/chapters?grade=7` |
| Survey | `POST` | `/api/v1/assessment-engine/amplitude/survey` |
| Fixed 10-item quiz | `GET` | `/api/v1/assessment-engine/amplitude/quiz?grade=7` |
| Evaluate | `POST` | `/api/v1/assessment-engine/amplitude/evaluate` |
| Read category (C1 / frontend) | `GET` | `/api/v1/assessment-engine/students/{student_id}/initial-category` |

### Survey rules

- Show **all chapters for the student’s grade** (use `/amplitude/chapters`).
- Student multi-selects completed chapters; **`completed_chapter_ids: []` is valid** (not started the grade).
- **`past_grade_marks_range` is mandatory:** `BELOW_50` | `50_75` | `ABOVE_75`.
- Same survey instrument for grades 6–9; only the chapter list is grade-scoped.

```json
{
  "user_id": "mock-student-class-a",
  "grade": 7,
  "completed_chapter_ids": [],
  "past_grade_marks_range": "50_75",
  "study_hours_per_week": 5.0,
  "self_confidence": 3,
  "science_self_efficacy": 4,
  "prerequisite_ready_count": 3
}
```

Optional research fields:

- `science_self_efficacy` (1–5): *I can figure out science questions even when they are new or a bit hard.*
- `prerequisite_ready_count` (0–5): how many of the five checklist items were ticked (reading, diagrams, following steps, explaining in own words, measurements).

### Quiz bank note

Placement items live in **`question_engine.amplitude_questions`** (exactly 10 MCQ/TrueFalse per grade). They are **not** taken from the adaptive `questions` bank.

Generate locally:

```powershell
python -m scripts.generate_amplitude_bank
python -m scripts.generate_amplitude_bank --grade 7
python -m scripts.generate_amplitude_bank --grade 6 --force
```

Difficulty uses **Aptitude Baseline Ladder (ABL)**: ABL-1 Recall ×4, ABL-2 Apply ×4, ABL-3 Connect ×2 (7 MCQ + 3 True/False). Ten chapters are **evenly spaced** through the grade ToC (one Topic ID each); stems that paraphrase an earlier slot (MiniLM cosine ≥ 0.82) are rejected.

### Evaluate

```json
{
  "user_id": "mock-student-class-a",
  "grade": 7,
  "completed_chapter_ids": ["G7_C1", "G7_C2"],
  "past_grade_marks_range": "50_75",
  "study_hours_per_week": 5.0,
  "self_confidence": 3,
  "science_self_efficacy": 4,
  "prerequisite_ready_count": 3,
  "answers": { "<question_id>": "B" }
}
```

---

## 2) Component 1 & Component 3 → Component 2 (sessions)

Shared chapter IDs: `G{grade}_C{chapter}` from [`data/chapter_ids_g6_g9.csv`](data/chapter_ids_g6_g9.csv). Never send `"8"` or `"Chapter 8"`.

### Customizable adaptive quiz

| Step | Method | Path |
|------|--------|------|
| Create | `POST` | `/api/v1/assessment-engine/quizzes/customizable` |
| Next | `GET` | `/api/v1/assessment-engine/quizzes/{session_id}/next` |
| Answer | `POST` | `/api/v1/assessment-engine/quizzes/{session_id}/answer` |
| Results | `GET` | `/api/v1/assessment-engine/quizzes/{session_id}/results` |

Create body:

```json
{
  "student_id": "mock-student-class-a",
  "grade": 6,
  "chapters": ["G6_C8", "G6_C7"],
  "num_questions": 5
}
```

Answer body:

```json
{
  "question_id": "<uuid from /next>",
  "student_answer": "B",
  "time_taken_seconds": 28.4
}
```

### Post-lesson quiz (Lesson Engine / Engagement)

`POST /api/v1/assessment-engine/quizzes/post-lesson`

```json
{
  "student_id": "mock-student-class-a",
  "chapter_id": "G6_C8",
  "grade": 6
}
```

Then the same `/next` + `/answer` loop (`max_questions` = 15).

### Kill switch (Component 3)

`POST /api/v1/assessment-engine/quizzes/{session_id}/terminate`

```json
{
  "reason": "frustration_threshold",
  "source": "component_3"
}
```

### Student category for Lesson Engine

`GET /api/v1/assessment-engine/students/{student_id}/initial-category`

### History

| Method | Path |
|--------|------|
| `GET` | `/api/v1/assessment-engine/students/{id}/sessions` |
| `GET` | `/api/v1/assessment-engine/students/{id}/sessions/{session_id}` |
| `POST` | `/api/v1/assessment-engine/students/{id}/sessions/{session_id}/analyze` |

More frontend detail: [`docs/FRONTEND_INTEGRATION.md`](docs/FRONTEND_INTEGRATION.md). Peer activation: [`INTEGRATION_STEPS.md`](INTEGRATION_STEPS.md).

---

## 3) Component 4 (outbound from Component 2)

Do **not** call Component 4 from the browser. Component 2 owns:

1. `POST {COMPONENT_4_URL}/api/v1/quiz/bkt-snapshot` at quiz start  
2. `POST {COMPONENT_4_URL}/api/v1/assessment-submit` after each graded `/answer`

**Contracts (do not fork conflicting copies):**

- Attempt payload / distractor tags / null fields: [`docs/COMPONENT2_COMPONENT4_INTEGRATION.md`](docs/COMPONENT2_COMPONENT4_INTEGRATION.md)
- BKT snapshot + `chapter_ids`: [`docs/QuestionEngine-BKT-Snapshot.md`](docs/QuestionEngine-BKT-Snapshot.md)

`PEER_HTTP_LIVE = False` → mocks; set `True` in `peers.py` when C4 is reachable.

---

## 4) Mock users

| user_id | role | class_code |
|---------|------|------------|
| `mock-student-unassigned` | student | — |
| `mock-student-class-a` | student | `CLASS-A` |
| `mock-teacher-1` | teacher | `CLASS-A` |

```powershell
python -m scripts.db.seed_mock_users
```

---

## 5) Local verify

```powershell
python -m scripts.init_postgres
python -m scripts.qa.test_amplitude_scoring
python -m scripts.qa.test_amplitude_evaluate
python -m scripts.generate_amplitude_bank --grade 6
```
