# Question Engine Integration — Component 2 → Component 4

**From:** Component 4 — Learner Profile Analytics & GenAI Support  
**To:** Component 2 — Intelligent Science Assessment / Question Engine  
**Endpoint:** `POST /api/v1/assessment-submit`  
**Base URL (local dev):** `http://127.0.0.1:8000`  
**When to call:** **Once per scored question attempt**, immediately after the student submits an answer and you know if it is correct or wrong.

For the full cross-component overview, see [`INTEGRATIONS.md`](../INTEGRATIONS.md).

---

## Shared prerequisite: `topic_id`

All payloads must use **`topic_id`** strings from our shared curriculum file:

**File:** `Data/Skill-Heirarchies-G6-G9.xlsx`  
**Column:** `Topic ID (Mocked for Assessment Module)`

Examples: `G6_S8_ELE_CONDINS`, `G8_S3_PHO_PROCESS`, `G9_S3_LIG_REFRAC`  
(57 topics, Grades 6–9 — **exact match**, case-sensitive.)

This is the **lesson/skill key** for the whole ecosystem. It is **not** a RAG chunk ID or PDF page reference.

---

## Complete field list

| Field | Type | Required | When | Purpose in Component 4 |
|-------|------|----------|------|-------------------------|
| `user_id` | string | **Yes** | Every attempt | Links attempt to learner (BKT, profile, dashboard) |
| `topic_id` | string | **Yes** | Every attempt | Skill/lesson key for BKT mastery & analytics |
| `is_correct` | boolean | **Yes** | Every attempt | Updates BKT mastery (`true` = correct, `false` = incorrect) |
| `question_type` | string | **Recommended** | Every attempt | `"MCQ"` or `"SHORT_ANSWER"` — tells us how to interpret other fields |
| `distractor_tag` | string (enum) | **Yes if wrong MCQ** | Wrong MCQ only | Error **category** for analytics |
| `distractor_label` | string | **Yes if wrong MCQ** | Wrong MCQ only | Short **description** of the misconception (Misconception Cloud) |
| `similarity_score` | float 0.0–1.0 | **Recommended** | Short answer | How close student answer was to marking scheme |
| `response_time_s` | float | Optional | Any | Seconds taken to answer (future analytics / BKT tuning) |
| `difficulty_level` | number | Optional | Any | Item difficulty (your scale, e.g. 1–5) |
| `subtopic_id` | string | Optional | Any | Finer label (e.g. `chlorophyll`) — **not** a replacement for `topic_id` |
| `question_id` | string | Optional | Any | Stable id for this question item (audit / dedupe) |
| `chosen_distractor_text` | string | Optional | Wrong MCQ | Full text of wrong option (backup if `distractor_label` missing) |
| `source` | string | Optional | Any | Your module version, e.g. `"question_engine_v1"` |

### `distractor_tag` allowed values (MCQ, wrong only)

| Value | Meaning |
|-------|---------|
| `NEAR_MISS` | Close to correct; small slip or partial understanding |
| `MISCONCEPTION` | Systematic wrong idea / common misconception |
| `COMPLETE_MISS` | Unrelated or random guess |

### `distractor_label` guidelines

- One short phrase (about **5–12 words**), e.g. `"Treats rubber as a conductor"`.
- Describes **what the wrong choice reveals**, not the full question text.
- Reuse the **same label** when the same misconception appears again (so counts aggregate cleanly).
- **Omit** when `is_correct` is `true`.

### Short answers — `is_correct` vs `similarity_score`

Send both when available:

- **`is_correct`** — authoritative label for BKT mastery updates.
- **`similarity_score`** — stored for analytics.

Suggested alignment (confirm as a team): `is_correct = true` when `similarity_score >= 0.70`.

---

## Example payloads

### 1) Correct MCQ

```json
{
  "user_id": "student_001",
  "topic_id": "G6_S8_ELE_CONDINS",
  "is_correct": true,
  "question_type": "MCQ",
  "response_time_s": 28.4,
  "difficulty_level": 2,
  "question_id": "q_g6_ele_014",
  "source": "question_engine_v1"
}
```

### 2) Wrong MCQ (feeds Misconception Cloud)

```json
{
  "user_id": "student_001",
  "topic_id": "G6_S8_ELE_CONDINS",
  "is_correct": false,
  "question_type": "MCQ",
  "distractor_tag": "MISCONCEPTION",
  "distractor_label": "Treats rubber covering as the conductor",
  "chosen_distractor_text": "Rubber wires carry electricity because they wrap the metal",
  "response_time_s": 45.2,
  "difficulty_level": 3,
  "question_id": "q_g6_ele_014",
  "subtopic_id": "conductors_insulators",
  "source": "question_engine_v1"
}
```

### 3) Wrong MCQ — near miss

```json
{
  "user_id": "student_001",
  "topic_id": "G7_S3_ELE_CURRENTS",
  "is_correct": false,
  "question_type": "MCQ",
  "distractor_tag": "NEAR_MISS",
  "distractor_label": "Confuses current with voltage",
  "response_time_s": 33.0,
  "question_id": "q_g7_cur_008",
  "source": "question_engine_v1"
}
```

### 4) Short answer — partial credit wrong

```json
{
  "user_id": "student_001",
  "topic_id": "G8_S3_PHO_PROCESS",
  "is_correct": false,
  "question_type": "SHORT_ANSWER",
  "similarity_score": 0.45,
  "response_time_s": 90.0,
  "question_id": "q_g8_pho_003",
  "source": "question_engine_v1"
}
```

### 5) Short answer — correct

```json
{
  "user_id": "student_001",
  "topic_id": "G8_S3_PHO_PROCESS",
  "is_correct": true,
  "question_type": "SHORT_ANSWER",
  "similarity_score": 0.88,
  "response_time_s": 52.0,
  "question_id": "q_g8_pho_003",
  "source": "question_engine_v1"
}
```

---

## What Component 4 does with each field

| Field | Used for |
|-------|----------|
| `user_id` + `topic_id` + `is_correct` | **BKT mastery** (teacher heatmap, at-risk alerts, student profile) |
| `distractor_tag` + `distractor_label` | **Misconception Cloud** — we **count** how often each label appears per student |
| `similarity_score` | Short-answer analytics (student profile; future charts) |
| `response_time_s`, `difficulty_level` | Stored for Phase 2 analytics; optional BKT use later |
| `question_id`, `subtopic_id` | Audit trail, drill-down later |
| `chosen_distractor_text` | Fallback display if `distractor_label` is missing |

**Not required in Phase 2:** full question text or correct answer text for the chatbot (may be added later for tutor–quiz linking).

### Division of responsibility

| Component 2 (Question Engine) | Component 4 (Analytics Hub) |
|-------------------------------|----------------------------|
| Score each attempt | Store each attempt |
| Set `is_correct` | Update BKT mastery from `is_correct` |
| On wrong MCQ: set `distractor_tag` + `distractor_label` | Aggregate label counts → **Misconception Cloud** |
| On short answer: compute `similarity_score` | Store for analytics; BKT uses `is_correct` |

**Misconception Cloud:** you **classify and name** each wrong MCQ; we **count and plot** frequent labels in the teacher dashboard.

---

## What we do *not* need from Question Engine (Phase 2)

- PDF chunks / RAG chunk IDs (each component maintains its own RAG index).
- Full question text or LLM prompts (unless we add tutor–quiz linking later).
- Frustration scores — those go to **Component 3** via `POST /api/v1/engagement/frustration-cue`.

## Quick summary

> Send **one POST per answered question** with `user_id`, `topic_id`, and `is_correct`.  
> On **wrong MCQs**, also send `distractor_tag` and `distractor_label`.  
> On **short answers**, send `similarity_score`.  
> Use **`topic_id`** values from `Skill-Heirarchies-G6-G9.xlsx` only.  
> Component 4 aggregates `distractor_label` counts for the teacher Misconception Cloud; Question Engine generates those labels when scoring.

---


