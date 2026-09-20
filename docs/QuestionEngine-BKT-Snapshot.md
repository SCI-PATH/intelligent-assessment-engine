# Question Engine — Quiz BKT Snapshot Contract

**From:** Component 4 — Learner Profile Analytics & GenAI Support  
**To:** Component 2 — Intelligent Science Assessment / Question Engine  
**Status:** Implemented (backward compatible)

This is the integration note for **quiz start** and the **widened `assessment-submit` response**.  
The existing attempt payload (`user_id`, `topic_id`, `is_correct`, …) is **unchanged**.

Base URL (local): `http://127.0.0.1:8003` (use whatever port Component 4 is running on)  
OpenAPI / Swagger: `http://127.0.0.1:8003/docs` (restart Component 4 after pulling these changes).  
Look under **Mastery** for `POST /api/v1/quiz/bkt-snapshot`. `assessment-submit` now also shows optional `chapter_ids`.

---

## Ownership (do not invert this)

| Concern | Owner |
|---------|--------|
| BKT P(L) values | **Component 4** (source of truth) |
| Chapter → topic mapping | **Component 4** |
| Quiz generation / scoring / DDA | Component 2 |
| Persisting BKT in Component 2’s database | **Do not do this** |

Component 2 may keep the snapshot **in session memory only**. Refresh it:

1. Once at quiz start (`POST /api/v1/quiz/bkt-snapshot`)
2. After every scored answer (from the `assessment-submit` response)

---

## Shared IDs

### `user_id`

Same learner ID used on every Component 4 call.

### `chapter_id` (new for this contract)

Format:

```text
G{grade}_C{chapter}
```

Examples: `G6_C8`, `G6_C7`, `G8_C11`

**Shared catalog (send this file with this README):**  
`Data/chapter_ids_g6_g9.csv`

| column | example |
|--------|---------|
| `chapter_id` | `G6_C8` ← **this is what you send** |
| `grade` | `6` |
| `chapter` | `8` |
| `chapter_title` | Electricity for a Comfortable Life |
| `topic_id_1` / `topic_id_2` | `G6_C8_ELE_CIRCUITS`, `G6_C8_ELE_CONDINS` |

Do **not** invent chapter keys, and do **not** send `"8"` or `"Chapter 8"`. Copy `chapter_id` from that CSV.

- **Post-lesson quiz:** send one chapter, e.g. `["G6_C8"]`
- **Custom exam / retake:** send every selected chapter, e.g. `["G6_C8", "G6_C7", "G6_C4"]`

Component 4 expands each chapter to its topic IDs. You do not need a second mapping table.

Also accepted (normalized by Component 4): `g6_c8`, `G6-C8`, or a full topic id such as `G6_C8_ELE_CIRCUITS`.

### `topic_id`

Unchanged. Canonical skill IDs from `Data/Skill-Heirarchies-G6-G9-Full-Chapters.xlsx`, e.g. `G6_C8_ELE_CIRCUITS`.

---

## Categories (per user × topic)

There is **no overall quiz category**. Category is always **one learner + one `topic_id`**.

| `mastery_category` | Rule | Suggested DDA use |
|--------------------|------|-------------------|
| `basic` | P(L) &lt; 0.50 | Easier items / more scaffolding |
| `intermediate` | 0.50 ≤ P(L) &lt; 0.80 | On-level items |
| `advanced` | P(L) ≥ 0.80 | Harder / transfer items |

Use these names exactly (`basic` / `intermediate` / `advanced`).

---

## Unseen topics

Unseen `(user_id, topic_id)` pairs return the skill **prior** (a real BKT starting value, often around 0.25), **not** `null`.

| Field | Meaning |
|-------|---------|
| `mastery_probability` | Current P(L). Prior if never attempted. |
| `mastery_category` | Band for that P(L) |
| `attempts` | `0` if unseen |
| `seen` | `false` if unseen |

If DDA wants “start easy on a new topic”, key off `seen: false` / `attempts: 0`. Do not treat the prior as missing data.

---

## 1) Quiz initialization (new endpoint)

Call this **once**, before generating the first question (including retakes — historical BKT is already stored on Component 4).

```http
POST /api/v1/quiz/bkt-snapshot
Content-Type: application/json
```

### Request

```json
{
  "user_id": "student_001",
  "chapter_ids": ["G6_C8"]
}
```

Custom exam:

```json
{
  "user_id": "student_001",
  "chapter_ids": ["G6_C8", "G6_C7"]
}
```

This call is **read-only**. It does not record an attempt and does not change mastery.

### Success response

```json
{
  "success": true,
  "user_id": "student_001",
  "chapter_ids": ["G6_C8"],
  "unknown_chapter_ids": [],
  "topic_ids": ["G6_C8_ELE_CIRCUITS", "G6_C8_ELE_CONDINS"],
  "topics_by_chapter": {
    "G6_C8": ["G6_C8_ELE_CIRCUITS", "G6_C8_ELE_CONDINS"]
  },
  "topic_bkt": {
    "G6_C8_ELE_CIRCUITS": {
      "mastery_probability": 0.71,
      "mastery_category": "intermediate",
      "attempts": 12,
      "seen": true
    },
    "G6_C8_ELE_CONDINS": {
      "mastery_probability": 0.25,
      "mastery_category": "basic",
      "attempts": 0,
      "seen": false
    }
  },
  "mastery_category_thresholds": {
    "basic": "P(L) < 0.50",
    "intermediate": "0.50 <= P(L) < 0.80",
    "advanced": "P(L) >= 0.80"
  }
}
```

If every `chapter_id` is invalid, `success` is `false` and `unknown_chapter_ids` lists what was rejected.

---

## 2) During the quiz (existing endpoint, extra response fields)

Keep posting **one scored attempt** as before:

```http
POST /api/v1/assessment-submit
Content-Type: application/json
```

Required body is unchanged: `user_id`, `topic_id`, `is_correct`, plus the existing enrichment fields.

### Optional new request field

| Field | Required? | Purpose |
|-------|-----------|---------|
| `chapter_ids` | No | Active quiz chapters. **Send this on custom exams / multi-chapter retakes.** |

- **Omitted / empty:** Component 4 returns `topic_bkt` for **only the answered topic’s chapter** (two skills). Existing clients keep working.
- **Provided:** `topic_bkt` covers every topic in those chapters, so session memory stays complete when the quiz jumps chapters.

Example (custom exam):

```json
{
  "user_id": "student_001",
  "topic_id": "G6_C8_ELE_CIRCUITS",
  "is_correct": true,
  "question_type": "MCQ",
  "question_id": "a1b2c3d4-0001-4000-8000-000000000001",
  "source": "question_engine_v1",
  "chapter_ids": ["G6_C8", "G6_C7"]
}
```

### Response — existing fields (unchanged)

These still describe **the topic that was just answered**:

| Field | Meaning |
|-------|---------|
| `updated_mastery_probability` / `mastery_probability` | New P(L) for that `topic_id` |
| `mastery_category` | `basic` / `intermediate` / `advanced` for that `topic_id` |
| `risk_flag` | Mastery dropped this attempt, or 3 incorrect in a row |

### Response — added fields (safe to ignore until wired)

Same shape as the snapshot endpoint:

| Field | Meaning |
|-------|---------|
| `chapter_ids` | Chapters actually resolved |
| `unknown_chapter_ids` | Any keys Component 4 could not resolve |
| `topic_ids` | All skills in that scope |
| `topics_by_chapter` | Chapter → topic list |
| `topic_bkt` | Full map for active chapters **after** this attempt |

Replace Component 2 session memory with `topic_bkt` after every successful POST. The answered topic’s row is already updated.

---

## What Component 2 should implement

1. **Quiz start:** `POST /api/v1/quiz/bkt-snapshot` with `user_id` + selected `chapter_ids`. Store `topic_bkt` in session memory.
2. **Each answer:** keep forwarding the scored payload to `POST /api/v1/assessment-submit`.
3. **Custom / multi-chapter quizzes:** also send `chapter_ids` on that POST.
4. **Next question:** read `topic_bkt[topic_id].mastery_category` (and `seen`) from session memory. Do not persist those numbers.
5. Do **not** build a parallel BKT store or a duplicate chapter → topic table.

---

## Backward compatibility

- Old `assessment-submit` request bodies (no `chapter_ids`) still validate and still update BKT.
- Old response fields are still present and still mean the same thing.
- `GET /api/v1/mastery/{user_id}/{topic_id}` is unchanged if a one-topic read is needed.

---

## Related

- Attempt payload details: [`QuestionEngine-Integration.md`](./QuestionEngine-Integration.md)
- Cross-component overview: [`../INTEGRATIONS.md`](../INTEGRATIONS.md)
