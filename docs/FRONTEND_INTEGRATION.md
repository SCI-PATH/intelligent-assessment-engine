# Frontend Integration README — Component 2 (Intelligent Assessment Engine)

Copy this file into the Next.js (or other) frontend repo. It is the **complete UI/API contract** for building the student + teacher experiences against Component 2.

Team peer/C4 handshake summary: see also root [`INTEGRATION_README.md`](../INTEGRATION_README.md).

| | |
|--|--|
| **Base URL (local)** | `http://localhost:8001` |
| **API prefix** | `/api/v1/assessment-engine` |
| **Swagger (live contract)** | `http://localhost:8001/docs` |
| **OpenAPI JSON** | `http://localhost:8001/openapi.json` |
| **Auth** | none (research phase) |
| **Headers** | `Content-Type: application/json` · `Accept: application/json` |

Errors: FastAPI `{ "detail": string | object }`.  
Pass mark on graded items: `is_correct` when `accuracy_score >= 0.8`.

**Do not call Component 4 from the browser.** Component 2 owns BKT snapshot + `assessment-submit` after grading.

Peer hosts live in backend `src/iae/config/peers.py` only.

---

## Suggested frontend modules

| Module | Screens / jobs |
|--------|----------------|
| `features/amplitude/` | Post-signup placement: survey → 10-item quiz → category result |
| `features/quiz/` | Customizable adaptive quiz + post-lesson loop |
| `features/history/` | Past sessions, detail, optional AI analysis |
| `features/teacher/` | Topic list, generate, review/approve/reject bank |
| `features/dev-hub/` | Temporary buttons for all flows (optional) |

Mock users (seeded):

| `user_id` / `student_id` | Role | `class_code` |
|--------------------------|------|--------------|
| `mock-student-unassigned` | student | — |
| `mock-student-class-a` | student | `CLASS-A` |
| `mock-teacher-1` | teacher | `CLASS-A` |

---

## Shared UI conventions

### Grade selector (all student flows)

- **Control:** dropdown / select  
- **Values:** `6` | `7` | `8` | `9`  
- **API field:** `grade` (integer)

### Chapter IDs (never free-text titles in create-quiz APIs)

Canonical form: `G{grade}_C{chapter}` e.g. `G6_C8`, `G7_C5`.

- Source of truth for Amplitude multi-select:  
  `GET /api/v1/assessment-engine/amplitude/chapters?grade=7`  
- Same catalog: repo file `data/chapter_ids_g6_g9.csv`  
- **Never** send `"8"` or `"Chapter 8"` as a chapter id

### Question types (rendering)

| `question_type` | Student UI | Answer format |
|-----------------|------------|---------------|
| `MCQ` | Stem + 4 radio options A–D from `prompt.options` | `"A"` / `"B"` / `"C"` / `"D"` |
| `TrueFalse` | Stem + True / False | `"True"` / `"False"` (capital T/F) |
| `ShortAnswer` | Stem + text input | free string |
| `MultiBlank` | `prompt.paragraph` with blanks + inputs | backend-specific; prefer matching blank order |

**Never show** to students: `correct_answer`, `ideal_answer`, `answers`, `keywords`, `option_diagnostics`, `distractor_tag`, `distractor_label`. Amplitude `/quiz` already strips these; adaptive `/next` may return full `Question` — strip secrets in the FE.

---

## Feature 1 — Amplitude placement (post-registration / pre-lessons)

**Goal:** Classify student as `BASIC` | `INTERMEDIATE` | `ADVANCED` before lessons.  
**Scoring:** 60% quiz + 40% survey composite (backend). No BKT.

### Screens / controls

1. **Survey screen**
   - Grade dropdown (6–9)
   - **Past science marks** (required) dropdown: `BELOW_50` | `50_75` | `ABOVE_75`
   - **Chapters completed** multi-select: load via `/amplitude/chapters?grade=` — show `chapter_title`, submit `chapter_id` list  
     - Allow **select none** (`[]`) = student has not started the grade
   - Study hours / week (number, 0–40, optional)
   - Self-confidence slider 1–5 (optional)
   - Science self-efficacy slider 1–5 — label: *“I can figure out science questions even when they are new or a bit hard.”*
   - Prerequisite checklist (5 checkboxes) — send **count** 0–5 as `prerequisite_ready_count`:
     1. I can understand a short science paragraph and say what it is mainly about  
     2. I can read a labelled diagram, table, or simple graph in science  
     3. I can follow step-by-step instructions for a science activity or experiment  
     4. I can explain a science idea in my own words (not only memorize facts)  
     5. I can use simple measurements in science (length, time, mass, or temperature)
2. **Quiz screen** — exactly 10 items (MCQ + True/False only); same set for every student in that grade
3. **Result screen** — show `category` + optional `weighted_score`; persist via `initial-category` for Lesson Engine

### Endpoints

| Step | Method | Path |
|------|--------|------|
| Chapters for multi-select | `GET` | `/api/v1/assessment-engine/amplitude/chapters?grade=7` |
| Save survey | `POST` | `/api/v1/assessment-engine/amplitude/survey` |
| Load quiz | `GET` | `/api/v1/assessment-engine/amplitude/quiz?grade=7` |
| Evaluate | `POST` | `/api/v1/assessment-engine/amplitude/evaluate` |
| Read category | `GET` | `/api/v1/assessment-engine/students/{student_id}/initial-category` |

#### Chapters response (example shape)

```json
{
  "grade": 7,
  "count": 19,
  "chapters": [
    {
      "chapter_id": "G7_C1",
      "chapter": 1,
      "chapter_title": "Plant Diversity",
      "topic_ids": ["G7_C1_PLA_DIVER", "G7_C1_PLA_CLASSIF"]
    }
  ]
}
```

#### Survey body

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

- `past_grade_marks_range` is **required**
- Prefer `completed_chapter_ids` (including `[]`). Legacy `completed_chapters_count` alone is still accepted

#### Quiz response

```json
{
  "grade": 7,
  "count": 10,
  "questions": [
    {
      "id": "<uuid>",
      "chapter_name": "...",
      "topic_id": "G7_C5_ACI_IDENTIF",
      "skill": "...",
      "dok_level": 1,
      "question_type": "MCQ",
      "grade": 7,
      "prompt": {
        "type": "MCQ",
        "question": "...",
        "options": { "A": "...", "B": "...", "C": "...", "D": "..." }
      }
    }
  ]
}
```

`dok_level` here is the **Amplitude Baseline Ladder** level (1–3), not adaptive-bank DOK 1–4.

**409** if bank missing for that grade (ops must run `python -m scripts.generate_amplitude_bank`).

#### Evaluate body

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
  "answers": {
    "<question_id_1>": "B",
    "<question_id_2>": "True"
  }
}
```

Response includes `category`, `quiz_score`, `history_score`, `weighted_score`, etc.

#### Initial category (Lesson Engine / FE)

`GET /api/v1/assessment-engine/students/mock-student-class-a/initial-category`

```json
{
  "student_id": "mock-student-class-a",
  "initial_category": "INTERMEDIATE",
  "initial_category_score": 0.62,
  "placement_category": "INTERMEDIATE"
}
```

---

## Feature 2 — Customizable adaptive quiz (Elo DDA)

### Screens / controls

- Grade dropdown (6–9)
- **Chapter multi-select** (required ≥1) — use `/amplitude/chapters?grade=` or CSV; submit `chapter_id`s
- Number of questions (1–30, default 5)
- Optional question-type multi-select: `MCQ` | `TrueFalse` | `ShortAnswer` | `MultiBlank` (omit = all)
- Loop: show `/next` → collect answer + optional timer → `POST /answer` until `is_complete`

### Endpoints

| Step | Method | Path |
|------|--------|------|
| Create | `POST` | `/api/v1/assessment-engine/quizzes/customizable` |
| Next | `GET` | `/api/v1/assessment-engine/quizzes/{session_id}/next` |
| Answer | `POST` | `/api/v1/assessment-engine/quizzes/{session_id}/answer` |
| Results | `GET` | `/api/v1/assessment-engine/quizzes/{session_id}/results` |

#### Create

```json
{
  "student_id": "mock-student-class-a",
  "grade": 6,
  "chapters": ["G6_C8", "G6_C7"],
  "num_questions": 5,
  "question_types": ["MCQ", "TrueFalse", "ShortAnswer", "MultiBlank"]
}
```

Response: `session_id`, `status`, `max_questions`, `elo_rating`, …

#### Answer

```json
{
  "question_id": "<uuid from /next>",
  "student_answer": "B",
  "time_taken_seconds": 28.4
}
```

Response: `grade` (GradeResult), `is_complete`, `elo_rating`, `status`.

Backend may call Component 4 (mocked if peers offline).

---

## Feature 3 — Post-lesson quiz (Component 1 / 3 → C2)

Triggered when a lesson finishes. FE or peer services call:

`POST /api/v1/assessment-engine/quizzes/post-lesson`

```json
{
  "student_id": "mock-student-class-a",
  "chapter_id": "G6_C8",
  "grade": 6
}
```

Returns a session with `max_questions` typically **15**. Then reuse the same `/next` + `/answer` loop as customizable.

**UI:** usually no chapter picker (chapter comes from lesson); show progress `questions_asked / max_questions`.

---

## Feature 4 — Kill switch (Component 3)

`POST /api/v1/assessment-engine/quizzes/{session_id}/terminate`

```json
{
  "reason": "frustration_threshold",
  "source": "component_3"
}
```

Idempotent if already ended. FE can show “session ended by engagement engine”.

---

## Feature 5 — Student history

| Method | Path | UI |
|--------|------|-----|
| `GET` | `/api/v1/assessment-engine/students/{id}/sessions` | List past quizzes |
| `GET` | `/api/v1/assessment-engine/students/{id}/sessions/{session_id}` | Detail / attempt trail |
| `POST` | `/api/v1/assessment-engine/students/{id}/sessions/{session_id}/analyze` | Optional “AI analysis” button |

Also: Amplitude category via `.../initial-category` (above).

---

## Feature 6 — Teacher hub

### Screens / controls

- Grade dropdown
- Topics table from `GET .../teacher/topics?grade=`
- Generate form: Topic ID select, DOK 1–4, question type, count
- Review queue: filter by `status` (`pending` / `approved` / `rejected`), grade, etc.
- Approve button / Reject form with reason enum + notes
- Optional “add custom question” form

### Endpoints

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/api/v1/assessment-engine/teacher/topics?grade=7` | Topic ID catalog |
| `POST` | `/api/v1/assessment-engine/teacher/generate` | RAG → `pending` items |
| `GET` | `/api/v1/assessment-engine/teacher/questions` | Filters: `status`, `grade`, … |
| `POST` | `/api/v1/assessment-engine/teacher/questions/{id}/approve` | |
| `POST` | `/api/v1/assessment-engine/teacher/questions/{id}/reject` | |
| `POST` | `/api/v1/assessment-engine/teacher/questions` | Manual add |

#### Reject body

```json
{
  "reason": "FACTUAL_ERROR",
  "notes": "Wrong polarity of magnet poles"
}
```

Reasons: `FACTUAL_ERROR` | `OUT_OF_SCOPE` | `POOR_PHRASING` | `TOO_EASY` | `TOO_HARD` | `OTHER`

#### Generate body

```json
{
  "topic_id": "G6_C7_MAG_POLES",
  "dok_level": 2,
  "question_type": "MCQ",
  "count": 1
}
```

---

## Health

`GET /` or health route (see Swagger **Health** tag) — use for deploy readiness.

---

## Full endpoint map (Component 2 inbound)

| Method | Path |
|--------|------|
| `GET` | `/api/v1/assessment-engine/amplitude/chapters` |
| `POST` | `/api/v1/assessment-engine/amplitude/survey` |
| `GET` | `/api/v1/assessment-engine/amplitude/quiz` |
| `POST` | `/api/v1/assessment-engine/amplitude/evaluate` |
| `POST` | `/api/v1/assessment-engine/quizzes/customizable` |
| `POST` | `/api/v1/assessment-engine/quizzes/post-lesson` |
| `GET` | `/api/v1/assessment-engine/quizzes/{session_id}/next` |
| `POST` | `/api/v1/assessment-engine/quizzes/{session_id}/answer` |
| `GET` | `/api/v1/assessment-engine/quizzes/{session_id}/results` |
| `POST` | `/api/v1/assessment-engine/quizzes/{session_id}/terminate` |
| `GET` | `/api/v1/assessment-engine/students/{student_id}/initial-category` |
| `GET` | `/api/v1/assessment-engine/students/{student_id}/sessions` |
| `GET` | `/api/v1/assessment-engine/students/{student_id}/sessions/{session_id}` |
| `POST` | `/api/v1/assessment-engine/students/{student_id}/sessions/{session_id}/analyze` |
| `GET` | `/api/v1/assessment-engine/teacher/topics` |
| `POST` | `/api/v1/assessment-engine/teacher/generate` |
| `GET` | `/api/v1/assessment-engine/teacher/questions` |
| `POST` | `/api/v1/assessment-engine/teacher/questions` |
| `POST` | `/api/v1/assessment-engine/teacher/questions/{question_id}/approve` |
| `POST` | `/api/v1/assessment-engine/teacher/questions/{question_id}/reject` |

Exact request/response fields: prefer live Swagger at `/docs` (generated from the same Pydantic models).

---

## Recommended user journeys

```text
Signup → Amplitude survey → Amplitude quiz → show category
     → (optional) Customizable quiz for practice
     → Lesson (C1) → Post-lesson quiz → History
Teacher → Topics → Generate → Review pending → Approve/Reject
Engagement (C3) → may terminate an active session
```

---

## Out of scope for FE (backend / peers)

- Component 4 `assessment-submit` / `bkt-snapshot` payloads — see `docs/COMPONENT2_COMPONENT4_INTEGRATION.md` and `docs/QuestionEngine-BKT-Snapshot.md`
- Cross-service peer URLs — `INTEGRATION_README.md` + `INTEGRATION_STEPS.md`

---

## Local smoke for FE developers

```powershell
# Backend running:
uvicorn iae.api.main:app --reload --port 8001
# Open http://localhost:8001/docs
```

Use Try-it-out with `mock-student-class-a` / grade `7` for Amplitude after the placement bank exists for that grade.
