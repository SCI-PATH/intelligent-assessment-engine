# Frontend Integration Guide — Component 2 (Intelligent Assessment Engine)

**Audience:** Next.js frontend developers / frontend AI agents.  
**Copy this file into the Next.js repo** and follow it as the integration contract.

**Base URL (local):** `http://localhost:8001`  
**Auth:** none (research phase)  
**API prefix:** `/api/v1/assessment-engine`  
**OpenAPI / Swagger:** `http://localhost:8001/docs`

```http
Content-Type: application/json
Accept: application/json
```

Errors: FastAPI `{ "detail": string | object }`  
Pass mark on graded items: `is_correct` when `accuracy_score >= 0.8`

---

## 0) Frontend architecture note

Suggested feature modules:

- `features/amplitude/`
- `features/quiz/` (customizable + post-lesson)
- `features/history/`
- `features/teacher/`
- `features/dev-hub/` ← temporary developer dashboard

Do **not** call Component 4 (`assessment-submit` / `bkt-snapshot`) from the browser.  
Component 2 owns those outbound calls after grading.

Shared chapter IDs: use `G{grade}_C{chapter}` from `data/chapter_ids_g6_g9.csv`, e.g. `G6_C8`.  
**Never** send `"8"` or `"Chapter 8"`.

---

## 1) Amplitude Diagnostic Test

Categories: **`BASIC` | `INTERMEDIATE` | `ADVANCED`** (no BKT).  
Scoring: 60% quiz + 40% historical composite.

| Step | Method | Path |
|------|--------|------|
| Survey | `POST` | `/api/v1/assessment-engine/amplitude/survey` |
| Fixed 10-item quiz | `GET` | `/api/v1/assessment-engine/amplitude/quiz?grade=7` |
| Evaluate | `POST` | `/api/v1/assessment-engine/amplitude/evaluate` |
| Read category (also for Component 1) | `GET` | `/api/v1/assessment-engine/students/{student_id}/initial-category` |

### Survey

```json
{
  "user_id": "mock-student-class-a",
  "grade": 7,
  "completed_chapters_count": 4,
  "past_grade_marks_range": "50_75",
  "study_hours_per_week": 5.0,
  "self_confidence": 3
}
```

`past_grade_marks_range`: `BELOW_50` | `50_75` | `ABOVE_75`  
`self_confidence`: 1–5  
`grade` may be injected for local testing before live profile integration.

### Evaluate

```json
{
  "user_id": "mock-student-class-a",
  "grade": 7,
  "completed_chapters_count": 4,
  "past_grade_marks_range": "50_75",
  "study_hours_per_week": 5.0,
  "self_confidence": 3,
  "answers": { "<question_id>": "B" }
}
```

Quiz prompts strip answer keys and distractor diagnostics.

---

## 2) Customizable adaptive quiz (Elo DDA)

| Step | Method | Path |
|------|--------|------|
| Create | `POST` | `/api/v1/assessment-engine/quizzes/customizable` |
| Next | `GET` | `/api/v1/assessment-engine/quizzes/{session_id}/next` |
| Answer | `POST` | `/api/v1/assessment-engine/quizzes/{session_id}/answer` |
| Results | `GET` | `/api/v1/assessment-engine/quizzes/{session_id}/results` |

### Create

```json
{
  "student_id": "mock-student-class-a",
  "grade": 6,
  "chapters": ["G6_C8", "G6_C7"],
  "num_questions": 5,
  "question_types": ["MCQ", "TrueFalse", "ShortAnswer", "MultiBlank"]
}
```

### Answer

```json
{
  "question_id": "<uuid from /next>",
  "student_answer": "B",
  "time_taken_seconds": 28.4
}
```

Backend fetches C4 BKT snapshot at start and forwards each graded attempt to C4.

---

## 3) Post-lesson quiz (Component 1 / Component 3 → Component 2)

| Method | Path |
|--------|------|
| `POST` | `/api/v1/assessment-engine/quizzes/post-lesson` |

```json
{
  "student_id": "mock-student-class-a",
  "chapter_id": "G6_C8",
  "grade": 6
}
```

Returns a session with `max_questions = 15`. Then use the same `/next` + `/answer` loop.

---

## 4) Kill switch (Component 3 → Component 2)

| Method | Path |
|--------|------|
| `POST` | `/api/v1/assessment-engine/quizzes/{session_id}/terminate` |

```json
{
  "reason": "frustration_threshold",
  "source": "component_3"
}
```

Idempotent if the session already ended.

---

## 5) Student history

| Method | Path |
|--------|------|
| `GET` | `/api/v1/assessment-engine/students/{id}/sessions` |
| `GET` | `/api/v1/assessment-engine/students/{id}/sessions/{session_id}` |
| `POST` | `/api/v1/assessment-engine/students/{id}/sessions/{session_id}/analyze` |

---

## 6) Teacher dashboard

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/api/v1/assessment-engine/teacher/topics?grade=7` | Excel Topic IDs |
| `POST` | `/api/v1/assessment-engine/teacher/generate` | RAG → pending |
| `GET` | `/api/v1/assessment-engine/teacher/questions` | Filters: `status`, `grade`, `class_code`, … |
| `POST` | `/api/v1/assessment-engine/teacher/questions/{id}/approve` | |
| `POST` | `/api/v1/assessment-engine/teacher/questions/{id}/reject` | reason enum |
| `POST` | `/api/v1/assessment-engine/teacher/questions` | custom add |

### Reject

```json
{
  "reason": "FACTUAL_ERROR",
  "notes": "Wrong polarity of magnet poles"
}
```

Reasons: `FACTUAL_ERROR` | `OUT_OF_SCOPE` | `POOR_PHRASING` | `TOO_EASY` | `TOO_HARD` | `OTHER`

---

## 7) Temporary Dev Hub

Build a temporary **Dev Hub** with buttons for Amplitude, Customizable, Post-lesson, Kill switch, History, Teacher.

Mock users:

| user_id | role | class_code |
|---------|------|------------|
| `mock-student-unassigned` | student | — |
| `mock-student-class-a` | student | `CLASS-A` |
| `mock-teacher-1` | teacher | `CLASS-A` |

---

## 8) Component 4 (outbound, owned by Component 2)

Documented in Swagger description and `docs/COMPONENT2_COMPONENT4_INTEGRATION.md`:

1. `POST {COMPONENT_4_URL}/api/v1/quiz/bkt-snapshot` at quiz start  
2. `POST {COMPONENT_4_URL}/api/v1/assessment-submit` after each graded `/answer`

---

## 9) How to explore contracts in Swagger

1. `uvicorn iae.api.main:app --reload --port 8001`  
2. Open `http://localhost:8001/docs`  
3. Tags: **Amplitude Diagnostic Test**, **Quizzes and Testing Loops**, **Student History**, **Teacher Hub**
