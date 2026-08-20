# Component 2 ↔ Component 4 Integration

**Component 2 (producer):** Intelligent Assessment Engine / Question Engine — *this repo*  
**Component 4 (consumer):** Learner Profile Analytics & BKT / Misconception Cloud  

After every scored diagnostic attempt, Component 2 **POSTs one JSON body** to the
endpoint **owned by Component 4**. This README is the contract for that body,
with a complete example for each of our **four** question types.

Inbound notes from Component 4:
- Attempt payload: this file (baseline)
- Quiz BKT snapshot (updates on top): [`docs/QuestionEngine-BKT-Snapshot.md`](docs/QuestionEngine-BKT-Snapshot.md)
- Chapter IDs: [`data/chapter_ids_g6_g9.csv`](data/chapter_ids_g6_g9.csv)

---

## Component 4 endpoint (where we send the payload)

| | |
|--|--|
| **Method / path** | `POST /api/v1/assessment-submit` |
| **Owner** | Component 4 |
| **Local base (C4)** | `http://127.0.0.1:8000` (or whatever port C4 runs on) |
| **Full URL** | `http://127.0.0.1:8000/api/v1/assessment-submit` |
| **When** | Once per scored attempt, immediately after Component 2 finishes grading |
| **Headers** | `Content-Type: application/json` · `Accept: application/json` |
| **Body** | Unified JSON below (same keys every time; unused fields are `null`) |

### Component 2 wiring

1. Student / frontend calls **our** API:  
   `POST http://localhost:8001/assessment/sessions/{session_id}/answer`
2. We grade → build the unified payload → save a local copy in  
   `question_engine.analytics_events`
3. We forward the **same JSON** to Component 4:

```http
POST {ANALYTICS_BASE_URL}/api/v1/assessment-submit
Content-Type: application/json
```

Set in `.env` (base only — path is appended in code):

```env
COMPONENT_4_URL=http://127.0.0.1:8003
ANALYTICS_BASE_URL=http://127.0.0.1:8003
```

If both are empty, the HTTP forward is skipped (local DB write still happens). Mock fallbacks keep the quiz loop alive.

**Also at quiz start** (see BKT snapshot doc): Component 2 calls  
`POST {COMPONENT_4_URL}/api/v1/quiz/bkt-snapshot` with `{ "user_id", "chapter_ids": ["G6_C8"] }`.  
On multi-chapter quizzes, `chapter_ids` is also attached to each `assessment-submit` body.

Implementation: `iae.infrastructure.clients.Component4Client` + `iae.application.analytics_payload`.

---

## Shared prerequisite: `topic_id`

Use Excel **Topic ID (Canonical)** strings only (case-sensitive), from:

`data/skills/Skill-Heirarchies-G6-G9-Full-Chapters.xlsx`  
→ synced to `src/iae/config/topics.yaml` via `python -m scripts.sync_skill_catalog`

Verified: **128** Excel Topic IDs match `topics.yaml` 1:1.

Examples from the workbook:

| Grade | Topic ID | Chapter |
|-------|----------|---------|
| 6 | `G6_C7_MAG_POLES` | Magnets |
| 6 | `G6_C8_ELE_CIRCUITS` | Electricity for a Comfortable Life |
| 7 | `G7_C5_ACI_IDENTIF` | Acids and Bases |
| 8 | `G8_C11_PHO_PROCESS` | Main Biological Processes in Plants |

`topic_id` = skill / lesson key for BKT.  
`subtopic_id` = optional finer label (`sub_concept`) — **not** a replacement for `topic_id`.

---

## Payload schema (body of `POST /api/v1/assessment-submit`)

Every request body contains **all** keys. Non-applicable values are explicitly `null`
(do not omit keys).

| Field | Type | Required | When populated | Purpose in Component 4 |
|-------|------|----------|----------------|-------------------------|
| `user_id` | string | **Yes** | Always | Learner key (BKT, profile, dashboard) |
| `topic_id` | string | **Yes** | Always | Skill key for BKT mastery |
| `is_correct` | boolean | **Yes** | Always | BKT update |
| `question_type` | string | **Yes** | Always | `MCQ` \| `ShortAnswer` \| `MultiBlank` \| `TrueFalse` |
| `question_id` | string | **Yes** | Always | Stable item id (audit / dedupe) |
| `distractor_tag` | string \| null | **Yes if wrong MCQ/TrueFalse** | Wrong MCQ or TrueFalse | Misconception category |
| `distractor_label` | string \| null | **Yes if wrong MCQ/TrueFalse** | Wrong MCQ or TrueFalse | Short misconception description |
| `chosen_distractor_text` | string \| null | Optional | Wrong MCQ or TrueFalse | Full wrong option text (`True`/`False` for TF) |
| `similarity_score` | float \| null | Recommended | ShortAnswer / MultiBlank | Closeness to marking scheme (0–1) |
| `error_category` | string \| null | Enrichment | ShortAnswer / MultiBlank | Diagnostic error class |
| `detailed_explanation` | string \| null | Enrichment | ShortAnswer / TrueFalse | 1–2 sentence explanation |
| `missed_blanks` | object \| null | Enrichment | MultiBlank | `{ "<index>": "<expected>" }` |
| `response_time_s` | float \| null | Optional | Always when client sends time | Seconds to answer |
| `difficulty_level` | number \| null | Optional | Always | DOK level 1–4 |
| `subtopic_id` | string \| null | Optional | When sub_concept set | Finer label |
| `source` | string | Optional | Always | `"question_engine_v1"` |

### Enums

**`distractor_tag` (wrong MCQ or TrueFalse):** `NEAR_MISS` | `MISCONCEPTION` | `COMPLETE_MISS`

**`error_category`:**  
- ShortAnswer: `NO_ERROR` \| `SPELLING_GRAMMAR_ERROR` \| `MISSING_KEYWORDS` \| `CONCEPTUAL_MISCONCEPTION` \| `COMPLETELY_IRRELEVANT`  
- MultiBlank: `NO_ERROR` \| `PARTIAL_MASTERY` \| `FULL_MISCONCEPTION`

**Pass mark:** Component 2 sets `is_correct = true` when `accuracy_score >= 0.8`.

### Field matrix by question type

| Field | MCQ | ShortAnswer | MultiBlank | TrueFalse |
|-------|-----|-------------|------------|-----------|
| `similarity_score` | `null` | set | set | `null` |
| `distractor_tag` / `distractor_label` / `chosen_distractor_text` | wrong only | `null` | `null` | wrong only |
| `error_category` | `null` | set | set | `null` |
| `detailed_explanation` | `null` | set | `null` | set (wrong) |
| `missed_blanks` | `null` | `null` | set | `null` |

---

## Exact request examples (Component 2 → Component 4)

These are the **JSON bodies** posted to:

`POST http://127.0.0.1:8000/api/v1/assessment-submit`

### 1) MCQ — correct

```http
POST /api/v1/assessment-submit HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json
```

```json
{
  "user_id": "student_001",
  "topic_id": "G6_C7_MAG_POLES",
  "question_id": "a1b2c3d4-0001-4000-8000-000000000001",
  "question_type": "MCQ",
  "is_correct": true,
  "similarity_score": null,
  "distractor_tag": null,
  "distractor_label": null,
  "chosen_distractor_text": null,
  "error_category": null,
  "detailed_explanation": null,
  "missed_blanks": null,
  "response_time_s": 28.4,
  "difficulty_level": 2,
  "subtopic_id": "Magnetic poles",
  "source": "question_engine_v1"
}
```

### 2) MCQ — wrong (Misconception Cloud)

```json
{
  "user_id": "student_001",
  "topic_id": "G6_C7_MAG_POLES",
  "question_id": "a1b2c3d4-0001-4000-8000-000000000001",
  "question_type": "MCQ",
  "is_correct": false,
  "similarity_score": null,
  "distractor_tag": "MISCONCEPTION",
  "distractor_label": "Treats like poles as attracting",
  "chosen_distractor_text": "South pole attracts another south pole",
  "error_category": null,
  "detailed_explanation": null,
  "missed_blanks": null,
  "response_time_s": 45.2,
  "difficulty_level": 2,
  "subtopic_id": "Magnetic poles",
  "source": "question_engine_v1"
}
```

### 3) MCQ — wrong near miss

```json
{
  "user_id": "student_001",
  "topic_id": "G6_C8_ELE_CIRCUITS",
  "question_id": "a1b2c3d4-0002-4000-8000-000000000002",
  "question_type": "MCQ",
  "is_correct": false,
  "similarity_score": null,
  "distractor_tag": "NEAR_MISS",
  "distractor_label": "Confuses series with parallel circuits",
  "chosen_distractor_text": "Current is the same in every branch of a parallel circuit",
  "error_category": null,
  "detailed_explanation": null,
  "missed_blanks": null,
  "response_time_s": 33.0,
  "difficulty_level": 3,
  "subtopic_id": "Simple circuits",
  "source": "question_engine_v1"
}
```

### 4) ShortAnswer — wrong / partial

```json
{
  "user_id": "student_001",
  "topic_id": "G8_C11_PHO_PROCESS",
  "question_id": "a1b2c3d4-0003-4000-8000-000000000003",
  "question_type": "ShortAnswer",
  "is_correct": false,
  "similarity_score": 0.45,
  "distractor_tag": null,
  "distractor_label": null,
  "chosen_distractor_text": null,
  "error_category": "MISSING_KEYWORDS",
  "detailed_explanation": "The answer omitted chlorophyll and light energy.",
  "missed_blanks": null,
  "response_time_s": 90.0,
  "difficulty_level": 3,
  "subtopic_id": "Photosynthesis process",
  "source": "question_engine_v1"
}
```

### 5) ShortAnswer — correct

```json
{
  "user_id": "student_001",
  "topic_id": "G8_C11_PHO_PROCESS",
  "question_id": "a1b2c3d4-0003-4000-8000-000000000003",
  "question_type": "ShortAnswer",
  "is_correct": true,
  "similarity_score": 0.88,
  "distractor_tag": null,
  "distractor_label": null,
  "chosen_distractor_text": null,
  "error_category": "NO_ERROR",
  "detailed_explanation": null,
  "missed_blanks": null,
  "response_time_s": 52.0,
  "difficulty_level": 3,
  "subtopic_id": "Photosynthesis process",
  "source": "question_engine_v1"
}
```

### 6) MultiBlank — partial mastery

```json
{
  "user_id": "student_001",
  "topic_id": "G7_C5_ACI_IDENTIF",
  "question_id": "a1b2c3d4-0004-4000-8000-000000000004",
  "question_type": "MultiBlank",
  "is_correct": false,
  "similarity_score": 0.5,
  "distractor_tag": null,
  "distractor_label": null,
  "chosen_distractor_text": null,
  "error_category": "PARTIAL_MASTERY",
  "detailed_explanation": null,
  "missed_blanks": {
    "1": "base"
  },
  "response_time_s": 61.0,
  "difficulty_level": 2,
  "subtopic_id": "Identification of acids and bases",
  "source": "question_engine_v1"
}
```

### 7) MultiBlank — all correct

```json
{
  "user_id": "student_001",
  "topic_id": "G7_C5_ACI_IDENTIF",
  "question_id": "a1b2c3d4-0004-4000-8000-000000000004",
  "question_type": "MultiBlank",
  "is_correct": true,
  "similarity_score": 1.0,
  "distractor_tag": null,
  "distractor_label": null,
  "chosen_distractor_text": null,
  "error_category": "NO_ERROR",
  "detailed_explanation": null,
  "missed_blanks": null,
  "response_time_s": 40.0,
  "difficulty_level": 2,
  "subtopic_id": "Identification of acids and bases",
  "source": "question_engine_v1"
}
```

### 8) TrueFalse — incorrect (with distractor tag/label)

```json
{
  "user_id": "student_001",
  "topic_id": "G6_C7_MAG_POLES",
  "question_id": "a1b2c3d4-0005-4000-8000-000000000005",
  "question_type": "TrueFalse",
  "is_correct": false,
  "similarity_score": null,
  "distractor_tag": "MISCONCEPTION",
  "distractor_label": "Believes like magnetic poles attract",
  "chosen_distractor_text": "False",
  "error_category": null,
  "detailed_explanation": "Opposite magnetic poles attract each other.",
  "missed_blanks": null,
  "response_time_s": 12.0,
  "difficulty_level": 1,
  "subtopic_id": "Magnetic poles",
  "source": "question_engine_v1"
}
```

### 9) TrueFalse — correct

```json
{
  "user_id": "student_001",
  "topic_id": "G6_C7_MAG_POLES",
  "question_id": "a1b2c3d4-0005-4000-8000-000000000005",
  "question_type": "TrueFalse",
  "is_correct": true,
  "similarity_score": null,
  "distractor_tag": null,
  "distractor_label": null,
  "chosen_distractor_text": null,
  "error_category": null,
  "detailed_explanation": null,
  "missed_blanks": null,
  "response_time_s": 8.5,
  "difficulty_level": 1,
  "subtopic_id": "Magnetic poles",
  "source": "question_engine_v1"
}
```

---

## End-to-end flow

```text
Frontend                         Component 2 (port 8001)              Component 4 (port 8000)
   |                                      |                                      |
   |  POST /assessment/sessions/{id}/answer                                     |
   |  { question_id, student_answer, time_taken_seconds }                       |
   |------------------------------------->|                                      |
   |                                      | grade + build unified payload        |
   |                                      | insert analytics_events (local)      |
   |                                      |                                      |
   |                                      |  POST /api/v1/assessment-submit      |
   |                                      |  (unified JSON body above)           |
   |                                      |------------------------------------->|
   |                                      |                                      | BKT + Misconception Cloud
   |  { grade, questions_asked, is_complete }                                    |
   |<-------------------------------------|                                      |
```

**Frontend never calls Component 4’s assessment-submit directly** for diagnostic
attempts — Component 2 does, after grading.

---

## Division of responsibility

| Component 2 | Component 4 |
|-------------|-------------|
| Own `POST /assessment/sessions/{id}/answer` for the frontend | Own `POST /api/v1/assessment-submit` for ingest |
| Score attempt; set `is_correct` | Update BKT from `is_correct` |
| Wrong MCQ / TrueFalse → `distractor_tag` + `distractor_label` (+ `chosen_distractor_text`) | Aggregate → Misconception Cloud |
| ShortAnswer / MultiBlank → `similarity_score` (+ `error_category` / `missed_blanks`) | Store for analytics charts |
| TrueFalse / ShortAnswer → `detailed_explanation` when wrong | Surface explanations in dashboards |
| Always send full key set (`null` when N/A) | Ignore `null` fields |

---

## `question_type` naming

Component 4’s early draft used `"SHORT_ANSWER"`. Component 2 sends the bank’s
canonical values — please accept these four strings:

- `MCQ`
- `ShortAnswer`
- `MultiBlank`
- `TrueFalse`

---

## Local checklist

**Component 2**

```powershell
# .env
ANALYTICS_BASE_URL=http://127.0.0.1:8000

$env:PYTHONPATH = "src"
uvicorn iae.api.main:app --reload --port 8001
```

**Component 4**

- Service listening on `http://127.0.0.1:8000`
- Route: `POST /api/v1/assessment-submit`
- Accept the unified JSON bodies in this file

**Smoke test body** (paste into Swagger / curl against C4):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/assessment-submit ^
  -H "Content-Type: application/json" ^
  -d "{\"user_id\":\"student_001\",\"topic_id\":\"G6_C7_MAG_POLES\",\"question_id\":\"q-test\",\"question_type\":\"MCQ\",\"is_correct\":false,\"similarity_score\":null,\"distractor_tag\":\"MISCONCEPTION\",\"distractor_label\":\"Treats like poles as attracting\",\"chosen_distractor_text\":\"South pole attracts another south pole\",\"error_category\":null,\"detailed_explanation\":null,\"missed_blanks\":null,\"response_time_s\":45.2,\"difficulty_level\":2,\"subtopic_id\":\"Magnetic poles\",\"source\":\"question_engine_v1\"}"
```

---

## Quick summary

> Frontend → Component 2 `…/answer` → grade → **POST same unified JSON to Component 4**  
> `POST /api/v1/assessment-submit`.  
> Always send all keys; use `null` when a field does not apply to that question type.  
> Wrong MCQ **or TrueFalse** must include `distractor_tag` + `distractor_label`.  
> ShortAnswer / MultiBlank must include `similarity_score`.  
> Use shared Excel `Topic ID (Canonical)` values only (`Skill-Heirarchies-G6-G9-Full-Chapters.xlsx`).
