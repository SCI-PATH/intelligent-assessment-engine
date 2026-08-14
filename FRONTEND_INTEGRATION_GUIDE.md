# Frontend Integration Guide

Copy-paste contract for the Next.js / React app (`src/components/features/assessment-engine/`).

**Base URL:** `http://localhost:8001`  
**Auth:** none (research phase). CORS is `*`.  
**Headers (all JSON POSTs):**

```http
Content-Type: application/json
Accept: application/json
```

**Errors:** FastAPI `{ "detail": string | object }`  
**Dates:** ISO-8601 (`2026-08-13T14:30:00.000000+00:00`)  
**Pass mark:** `is_correct` when `accuracy_score >= 0.8`  
**Diagnostic session length:** `max_questions` = **5** (from `app.yaml`)

There is no `POST /assessment/submit`. Grading is `POST /assessment/sessions/{session_id}/answer`.

Health: `GET /` → `{ "status": "ok", "service": "intelligent-assessment-engine" }`

---

## Shared TypeScript types

Paste this file as `types/assessment-engine.ts` (or similar).

```typescript
export type GradeYear = 6 | 7 | 8 | 9;
export type DokLevel = 1 | 2 | 3 | 4;

export type QuestionType = "MCQ" | "ShortAnswer" | "MultiBlank" | "TrueFalse";
export type QuestionStatus = "pending" | "approved" | "rejected";
export type QuestionOrigin = "ai" | "teacher";

export type PastGradeMarksRange = "BELOW_50" | "50_75" | "ABOVE_75";
export type PlacementCategory = "WEAK" | "AVERAGE" | "ADVANCED";

export type ShortAnswerErrorCategory =
  | "NO_ERROR"
  | "SPELLING_GRAMMAR_ERROR"
  | "MISSING_KEYWORDS"
  | "CONCEPTUAL_MISCONCEPTION"
  | "COMPLETELY_IRRELEVANT";

export type MultiBlankErrorCategory =
  | "NO_ERROR"
  | "PARTIAL_MASTERY"
  | "FULL_MISCONCEPTION";

export type DistractorTag = "NEAR_MISS" | "MISCONCEPTION" | "COMPLETE_MISS";
export type ErrorCategory = ShortAnswerErrorCategory | MultiBlankErrorCategory;

export type RuleTraceCategory = "dok" | "type" | "cold_start";

export interface TraceCondition {
  label: string;
  required: boolean;
  met: boolean | null;
  observed: string;
}

export interface RuleTrace {
  rule_id: string;
  title: string;
  category: RuleTraceCategory;
  pedagogy_tag: string;
  conditions: TraceCondition[];
  outcome: string;
}

export interface McqPayload {
  type: "MCQ";
  question: string;
  options: Record<string, string>; // "A" | "B" | "C" | "D"
  correct_answer: string;
}

export interface ShortAnswerPayload {
  type: "ShortAnswer";
  question: string;
  ideal_answer: string;
  keywords: string[];
}

export interface MultiBlankPayload {
  type: "MultiBlank";
  paragraph: string; // blanks rendered as ___
  answers: string[];
}

export interface TrueFalsePayload {
  type: "TrueFalse";
  question: string;
  correct_answer: "True" | "False";
}

export type QuestionPayload =
  | McqPayload
  | ShortAnswerPayload
  | MultiBlankPayload
  | TrueFalsePayload;

/** Full bank item. Diagnostic `/next` includes answer keys — do not render them to students. */
export interface Question {
  id: string;
  chapter_name: string;
  sub_concept: string;
  dok_level: DokLevel;
  question_type: QuestionType;
  payload: QuestionPayload;
  chunk_ids: string[];
  grade: number;
  topic_id: string;
  skill: string;
  status: QuestionStatus;
  origin: QuestionOrigin;
  created_at: string;
}

export interface GradeResult {
  accuracy_score: number; // 0..1
  is_correct: boolean;
  feedback: string;
  reasoning: string;
  error_category: ErrorCategory | null;
  missing_keywords: string[] | null;
  detailed_explanation: string | null;
  missed_blanks: Record<string, string> | null; // "0" -> expected answer
  concept_explanation: string | null;
  distractor_tag: DistractorTag | null;
  distractor_label: string | null;
}

export interface AttemptRecord {
  question_id: string;
  question_type: QuestionType;
  chapter_name: string;
  sub_concept: string;
  dok_level: DokLevel;
  student_answer: string;
  accuracy_score: number;
  is_correct: boolean;
  feedback: string;
  reasoning: string;
  adaptive_decision: string;
  decision_rule_triggered: string;
  decision_dok_reason: string;
  decision_question_type_reason: string;
  decision_prev_dok: DokLevel | null;
  decision_target_dok: DokLevel | null;
  decision_rolling_accuracy: number | null;
  decision_last_accuracy: number | null;
  decision_last_response_time_seconds: number | null;
  decision_dok_trace: RuleTrace | null;
  decision_type_trace: RuleTrace | null;
  time_taken_seconds: number;
  asked_at: string;
  error_category: ErrorCategory | null;
  missing_keywords: string[] | null;
  detailed_explanation: string | null;
  missed_blanks: Record<string, string> | null;
  concept_explanation: string | null;
  distractor_tag: DistractorTag | null;
  distractor_label: string | null;
}

export interface RlState {
  current_chapter: string;
  time_taken: number;
  response_time_seconds: number;
  accuracy_score: number;
  streak: number;
  current_difficulty: DokLevel;
  last_question_type: QuestionType | null;
  current_sub_concept: string | null;
}

export interface ActionTelemetry {
  target_chapter: string;
  next_difficulty_level: DokLevel;
  next_question_type: QuestionType;
  next_sub_concept: string;
  rule_triggered: string;
  dok_reason: string;
  question_type_reason: string;
  dok_summary: string;
  type_summary: string;
  dok_trace: RuleTrace | null;
  type_trace: RuleTrace | null;
  estimated_theta: number;
  item_b: number;
  previous_response_time_seconds: number;
  rapid_guessing_detected: boolean;
  format_simplification_triggered: boolean;
}

export interface TelemetryPayload {
  state: RlState;
  action: ActionTelemetry;
  rolling_accuracy: number;
  questions_asked: number;
}

export interface ApiError {
  detail: string;
}
```

### Student answer encoding

| `question_type` | `student_answer` |
|---|---|
| `MCQ` | Letter: `"A"` / `"B"` / `"C"` / `"D"` |
| `TrueFalse` | `"True"` or `"False"` (also accepts `T` / `F`) |
| `ShortAnswer` | Free text |
| `MultiBlank` | JSON array `["magnet","iron"]` **or** `magnet\|iron` / comma-separated |

---

## 1. Initial survey and placement quiz

Weighted category: `0.7 * (quiz_correct / quiz_total) + 0.3 * past_score`  
Past midpoints: `BELOW_50` → 0.25, `50_75` → 0.625, `ABOVE_75` → 0.875  
Bands: `WEAK` &lt; 50%, `AVERAGE` 50–75% inclusive, `ADVANCED` &gt; 75%.

Placement quiz prompts **strip** `correct_answer`, `ideal_answer`, `answers`, `keywords`.

### TypeScript

```typescript
export interface PlacementSurveyRequest {
  user_id: string;
  grade: GradeYear;
  completed_chapters_count: number; // >= 0
  past_grade_marks_range: PastGradeMarksRange;
}

export interface StudentProfile {
  user_id: string;
  grade: number | null;
  completed_chapters_count: number | null;
  past_grade_marks_range: PastGradeMarksRange | null;
  placement_category: PlacementCategory | null; // null until /evaluate
  placement_score: number | null;
  created_at: string;
  updated_at: string;
}

/** Discriminated by prompt.type; answer keys are omitted. */
export type PlacementPrompt =
  | { type: "MCQ"; question: string; options: Record<string, string> }
  | { type: "ShortAnswer"; question: string }
  | { type: "MultiBlank"; paragraph: string }
  | { type: "TrueFalse"; question: string };

export interface PlacementQuizItem {
  id: string;
  chapter_name: string;
  topic_id: string;
  skill: string;
  dok_level: DokLevel;
  question_type: QuestionType;
  grade: number;
  prompt: PlacementPrompt;
}

export interface PlacementQuizResponse {
  grade: number;
  count: number; // always 10 on success
  questions: PlacementQuizItem[];
}

export interface PlacementEvaluateRequest {
  user_id: string;
  grade: GradeYear;
  completed_chapters_count: number;
  past_grade_marks_range: PastGradeMarksRange;
  quiz_correct: number; // 0..quiz_total
  quiz_total?: number; // default 10
}

export interface PlacementEvaluation {
  id: string;
  user_id: string;
  grade: number;
  completed_chapters_count: number;
  past_grade_marks_range: PastGradeMarksRange;
  quiz_correct: number;
  quiz_total: number;
  quiz_score: number;
  past_score: number;
  weighted_score: number;
  category: PlacementCategory;
  created_at: string;
}
```

### `POST /assessment/placement/survey`

Upserts `question_engine.users`.

**Request**

```json
{
  "user_id": "learner-42",
  "grade": 6,
  "completed_chapters_count": 3,
  "past_grade_marks_range": "50_75"
}
```

**Response `200`** — `StudentProfile` (`placement_category` is `null` until evaluate).

**Errors:** `422` validation.

### `GET /assessment/placement/quiz?grade=6`

No body. Query: `grade` (6–9, default 6).

**Response `200`**

```json
{
  "grade": 6,
  "count": 10,
  "questions": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "chapter_name": "Magnets",
      "topic_id": "G6_C7_MAG_POLES",
      "skill": "Ch.7: Magnetic poles, types, and behaviour",
      "dok_level": 2,
      "question_type": "MCQ",
      "grade": 6,
      "prompt": {
        "type": "MCQ",
        "question": "Which pole seeks geographic north?",
        "options": { "A": "...", "B": "...", "C": "...", "D": "..." }
      }
    }
  ]
}
```

**Errors:** `409` if fewer than 10 `approved` items exist for that grade.

### `POST /assessment/placement/evaluate`

**Request**

```json
{
  "user_id": "learner-42",
  "grade": 6,
  "completed_chapters_count": 3,
  "past_grade_marks_range": "50_75",
  "quiz_correct": 7,
  "quiz_total": 10
}
```

**Response `200`**

```json
{
  "id": "…",
  "user_id": "learner-42",
  "grade": 6,
  "completed_chapters_count": 3,
  "past_grade_marks_range": "50_75",
  "quiz_correct": 7,
  "quiz_total": 10,
  "quiz_score": 0.7,
  "past_score": 0.625,
  "weighted_score": 0.6775,
  "category": "AVERAGE",
  "created_at": "2026-08-13T20:00:00+00:00"
}
```

Suggested UI flow: survey → quiz (collect 10 local answers) → evaluate with `quiz_correct`.

---

## 2. Diagnostic testing loop

Student serving is **approved** items only. Same `user_id` never receives the same `question_id` twice (`served_questions`).

`chapter_name` must match `GET /assessment/chapters?grade=` exactly (e.g. `"Magnets"`).

`/next` returns the full `Question` including keys. Hide `payload.correct_answer`, `ideal_answer`, `answers`, `keywords` in the student UI.

### TypeScript

```typescript
export interface ChaptersResponse {
  grade: number;
  chapters: string[];
  max_questions: number;
}

export interface CreateSessionRequest {
  chapter_name: string;
  grade?: GradeYear; // default 6
  user_id?: string | null; // server mints a UUID if omitted
}

export interface SessionResponse {
  session_id: string;
  user_id: string;
  scope_chapter: string;
  questions_asked: number;
  max_questions: number;
}

export interface NextQuestionResponse {
  question: Question;
  telemetry: TelemetryPayload;
}

export interface SubmitAnswerRequest {
  question_id: string;
  student_answer: string;
  time_taken_seconds?: number; // default 0
}

export interface SubmitAnswerResponse {
  grade: GradeResult;
  questions_asked: number;
  is_complete: boolean; // true when questions_asked >= max_questions (5)
}

export interface ResultsResponse {
  scope_chapter: string;
  questions_asked: number;
  correct_count: number;
  raw_accuracy: number;
  history: AttemptRecord[];
}
```

### `GET /assessment/chapters?grade=6`

**Response `200`**

```json
{
  "grade": 6,
  "chapters": [
    "Wonders of the Living World",
    "Things Around Us",
    "Water as a Natural Resource",
    "Energy in Day-to-Day Life",
    "Light and Vision",
    "Sound and Hearing",
    "Magnets",
    "Electricity for a Comfortable Life",
    "Heat and Its Effects",
    "Food-related Interactions",
    "Weather and Climate"
  ],
  "max_questions": 5
}
```

**Errors:** `400` unknown grade.

### `POST /assessment/sessions`

**Request**

```json
{
  "chapter_name": "Magnets",
  "grade": 6,
  "user_id": "learner-42"
}
```

**Response `200`**

```json
{
  "session_id": "50e1d154-0342-400b-bb32-81fc94cbaf99",
  "user_id": "learner-42",
  "scope_chapter": "Magnets",
  "questions_asked": 0,
  "max_questions": 5
}
```

**Errors:** `400` unknown chapter/grade.

### `POST /assessment/sessions/{session_id}/next`

No body.

**Response `200`** — `{ "question": Question, "telemetry": TelemetryPayload }`

**Errors:** `404` session missing · `409` bank exhausted or session already at `max_questions`.

### `POST /assessment/sessions/{session_id}/answer`

**Request**

```json
{
  "question_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "student_answer": "B",
  "time_taken_seconds": 12.5
}
```

**Response `200`**

```json
{
  "grade": {
    "accuracy_score": 0.0,
    "is_correct": false,
    "feedback": "Incorrect. The right answer is A.",
    "reasoning": "",
    "error_category": null,
    "missing_keywords": null,
    "detailed_explanation": null,
    "missed_blanks": null,
    "concept_explanation": null,
    "distractor_tag": "MISCONCEPTION",
    "distractor_label": "The student selected a related but incorrect magnetic idea."
  },
  "questions_asked": 1,
  "is_complete": false
}
```

Diagnostics by type (unused fields stay `null`):

| Type | When | Fields |
|---|---|---|
| Wrong MCQ | always | `distractor_tag`, `distractor_label` |
| ShortAnswer | always | `error_category`, `missing_keywords`, `detailed_explanation` |
| MultiBlank | always | `error_category`, `missed_blanks` |
| Wrong TrueFalse | always | `concept_explanation` (1 sentence) |

**Errors:** `404` session or question id.

Loop until `is_complete === true` (5 graded answers), then `GET .../results`.

### `GET /assessment/sessions/{session_id}/results`

**Response `200`** — `ResultsResponse` (`history` is `AttemptRecord[]`).

**Errors:** `404`.

### Suggested client loop

```typescript
const session = await api.post<SessionResponse>("/assessment/sessions", {
  chapter_name: chapter,
  grade,
  user_id,
});

while (true) {
  const { question, telemetry } = await api.post<NextQuestionResponse>(
    `/assessment/sessions/${session.session_id}/next`,
  );
  const student_answer = await collectAnswer(question); // hide keys
  const result = await api.post<SubmitAnswerResponse>(
    `/assessment/sessions/${session.session_id}/answer`,
    {
      question_id: question.id,
      student_answer,
      time_taken_seconds: elapsedSeconds,
    },
  );
  showGrade(result.grade);
  if (result.is_complete) break;
}

const summary = await api.get<ResultsResponse>(
  `/assessment/sessions/${session.session_id}/results`,
);
```

---

## 3. Teacher review and generation

No teacher auth. `POST /teacher/generate` stores **`pending`**. Offline bank generation stores **`approved`**. Students only see **`approved`**.

### TypeScript

```typescript
export interface TeacherTopicItem {
  grade: number;
  topic_id: string;
  chapter_title: string;
  skill: string;
  chapter_number: number | null;
  domain: string;
  concept_code: string;
}

export interface TeacherTopicsResponse {
  grade: number;
  topics: TeacherTopicItem[];
}

export interface GenerateQuestionsRequest {
  topic_id: string;
  skill?: string | null;
  dok_level?: DokLevel; // default 2
  question_type?: QuestionType; // default "MCQ"
  count?: number; // 1..8, default 1
}

export interface GenerateQuestionsResponse {
  created: number;
  questions: Question[]; // status: "pending"
}

export interface TeacherQuestionListResponse {
  questions: Question[];
}

export interface CreateTeacherQuestionRequest {
  grade?: GradeYear; // default 6
  chapter_name?: string;
  topic_id: string;
  skill?: string;
  dok_level: DokLevel;
  question_type: QuestionType;
  payload: QuestionPayload; // payload.type must equal question_type
  sub_concept?: string;
}
```

### `GET /teacher/topics?grade=6`

**Response `200`**

```json
{
  "grade": 6,
  "topics": [
    {
      "grade": 6,
      "topic_id": "G6_C7_MAG_POLES",
      "chapter_title": "Magnets",
      "skill": "Ch.7: Magnetic poles, types, and behaviour",
      "chapter_number": 7,
      "domain": "MAG",
      "concept_code": "POLES"
    }
  ]
}
```

### `POST /teacher/generate`

RAG + LLM. Items are `status: "pending"`, `origin: "ai"`.

**Request**

```json
{
  "topic_id": "G6_C7_MAG_POLES",
  "dok_level": 2,
  "question_type": "MCQ",
  "count": 1
}
```

**Response `200`:** `{ "created": 1, "questions": [ Question ] }`

**Errors:** `400` unknown `topic_id` · `409` no Chroma chunks for that topic · `429` LLM rate limit.

### `GET /teacher/questions`

Query: `status` (`pending` \| `approved` \| `rejected`), `topic_id`, `grade`, `limit` (1–500, default 100).

**Response `200`:** `{ "questions": Question[] }`

Review queue: `GET /teacher/questions?status=pending`.

### `POST /teacher/questions/{id}/approve`

No body. **Response `200`:** `Question` with `status: "approved"`. **Errors:** `404`.

### `POST /teacher/questions/{id}/reject`

No body. **Response `200`:** `Question` with `status: "rejected"`. **Errors:** `404`.

### `POST /teacher/questions`

Teacher-authored item, stored as **`approved`** / `origin: "teacher"`.

**Request**

```json
{
  "grade": 6,
  "chapter_name": "Magnets",
  "topic_id": "G6_C7_MAG_POLES",
  "skill": "Ch.7: Magnetic poles, types, and behaviour",
  "dok_level": 2,
  "question_type": "MCQ",
  "payload": {
    "type": "MCQ",
    "question": "Which pole of a bar magnet seeks geographic north?",
    "options": {
      "A": "North pole",
      "B": "South pole",
      "C": "Equator",
      "D": "A piece of wood"
    },
    "correct_answer": "A"
  }
}
```

**Response `200`:** `Question`. **Errors:** `400` unknown topic or `payload.type` ≠ `question_type`.

---

## Fetch helper (Next.js)

```typescript
const API_BASE =
  process.env.NEXT_PUBLIC_IAE_API_BASE ?? "http://localhost:8001";

async function iaeFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({ detail: res.statusText }))) as ApiError;
    throw new Error(typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail));
  }
  return res.json() as Promise<T>;
}
```

Env: `NEXT_PUBLIC_IAE_API_BASE=http://localhost:8001`.
