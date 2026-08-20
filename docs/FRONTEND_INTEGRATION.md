# Frontend Integration Guide — Component 2 (Intelligent Assessment Engine)

**Audience:** Next.js frontend developers / frontend AI agents.  
**Copy this file into the Next.js repo** and follow it as the integration contract.

**Base URL (local):** `http://localhost:8001`  
**Auth:** none (research phase)  
**Preferred API prefix:** `/api/v1`  
**OpenAPI / Swagger (authoritative schemas):** `http://localhost:8001/docs`

```http
Content-Type: application/json
Accept: application/json
```

Errors: FastAPI `{ "detail": string | object }`  
Pass mark on graded items: `is_correct` when `accuracy_score >= 0.8`

---

## 0) Frontend architecture note (mandatory)

Adhere to the Next.js repo’s `developer_readme.md` folder structure.

Suggested feature modules (names only — follow your repo’s conventions):

- `features/amplitude/`
- `features/quiz/` (customizable + post-lesson)
- `features/history/`
- `features/teacher/`
- `features/dev-hub/` ← temporary developer dashboard (see §7)

Do **not** call Component 4 (`assessment-submit` / `bkt-snapshot`) from the browser.  
Component 2 owns those outbound calls after grading.

Shared chapter IDs: use `G{grade}_C{chapter}` from Component 2’s catalog  
(`data/chapter_ids_g6_g9.csv`), e.g. `G6_C8`. **Never** send `"8"` or `"Chapter 8"`.

---

## 1) Amplitude Test (initial category)

Categories: **`BASIC` | `INTERMEDIATE` | `ADVANCED`** (no BKT).  
Scoring: 60% quiz + 40% historical composite.

| Step | Method | Path |
|------|--------|------|
| Survey | `POST` | `/api/v1/amplitude/survey` |
| Fixed 10-item quiz | `GET` | `/api/v1/amplitude/quiz?grade=7` |
| Evaluate | `POST` | `/api/v1/amplitude/evaluate` |
| Read category | `GET` | `/api/v1/student/{student_id}/initial-category` |

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

Quiz prompts strip answer keys. Response includes `category`, `weighted_score`, `quiz_score`, `history_score`.

---

## 2) Customizable adaptive quiz (Elo DDA)

| Step | Method | Path |
|------|--------|------|
| Create | `POST` | `/api/v1/quizzes/customizable` |
| Next | `GET` | `/api/v1/quizzes/{session_id}/next` |
| Answer | `POST` | `/api/v1/quizzes/{session_id}/answer` |
| Results | `GET` | `/api/v1/quizzes/{session_id}/results` |

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

## 3) Post-lesson quiz (Component 1 → Component 2)

| Method | Path |
|--------|------|
| `POST` | `/api/v1/quiz/trigger-post-lesson` |

```json
{
  "student_id": "mock-student-class-a",
  "chapter_id": "G6_C8",
  "grade": 6
}
```

Returns a session with `max_questions = 15`. Then use the same `/next` + `/answer` loop as customizable quizzes.

---

## 4) Kill switch (Component 3 → Component 2)

| Method | Path |
|--------|------|
| `POST` | `/api/v1/quiz/{session_id}/terminate` |

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
| `GET` | `/api/v1/student/{id}/sessions` |
| `GET` | `/api/v1/student/{id}/sessions/{session_id}` |
| `POST` | `/api/v1/student/{id}/sessions/{session_id}/analyze` |

Detail includes student answers + expected answers. Analyze returns constructive LLM feedback for wrong items.

---

## 6) Teacher dashboard

Prefer `/api/v1/teacher/*`.

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/api/v1/teacher/topics?grade=7` | Excel Topic IDs |
| `POST` | `/api/v1/teacher/generate` | RAG → pending |
| `GET` | `/api/v1/teacher/questions` | Filters: `status`, `grade`, `class_code`, `dok_level`, `question_type` |
| `POST` | `/api/v1/teacher/questions/{id}/approve` | |
| `POST` | `/api/v1/teacher/questions/{id}/reject` | reason enum |
| `POST` | `/api/v1/teacher/questions` | custom add |

### Reject

```json
{
  "reason": "FACTUAL_ERROR",
  "notes": "Wrong polarity of magnet poles"
}
```

Reasons: `FACTUAL_ERROR` | `OUT_OF_SCOPE` | `POOR_PHRASING` | `TOO_EASY` | `TOO_HARD` | `OTHER`  
On `FACTUAL_ERROR`, backend may set `rejection_confirmed_ai=true`.

---

## 7) Temporary Dev Hub (required for sprint testing)

Build a temporary **Dev Hub** route (e.g. `/dev-hub`) with buttons that open each flow independently before final UI polish:

1. **Amplitude** → survey form → load quiz → evaluate → show category  
2. **Customizable Quiz** → pick chapter_ids → start → next/answer loop → results  
3. **Post-lesson** → trigger with `chapter_id` → continue quiz loop  
4. **Kill switch** → terminate active `session_id`  
5. **Student History** → list sessions → detail → analyze  
6. **Teacher** → list questions → approve / reject with reason  

Mock users for local testing (seeded by Component 2):

| user_id | role | class_code |
|---------|------|------------|
| `mock-student-unassigned` | student | — |
| `mock-student-class-a` | student | `CLASS-A` |
| `mock-teacher-1` | teacher | `CLASS-A` |

Optional: add a user picker at the top of Dev Hub that sets `student_id` / teacher context.

---

## 8) Deprecated legacy paths (do not use for new UI)

- `/assessment/placement/*` (old WEAK/AVERAGE/ADVANCED)
- `/assessment/sessions/*` (old diagnostic-only loop)
- `/teacher/*` (prefer `/api/v1/teacher`)

---

## 9) How to explore contracts in Swagger

1. Start Component 2: `uvicorn iae.api.main:app --reload --port 8001`  
2. Open `http://localhost:8001/docs`  
3. Expand tags: **Amplitude**, **Quizzes**, **Student History**, **Teacher Hub**  
4. Click **Try it out** → fill JSON → **Execute**  
5. Sync TypeScript types from `http://localhost:8001/openapi.json` if desired
