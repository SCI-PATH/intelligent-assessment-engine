CREATE SCHEMA IF NOT EXISTS question_engine;

CREATE TABLE IF NOT EXISTS question_engine.questions (
    id UUID PRIMARY KEY,
    grade INTEGER NOT NULL,
    chapter_name TEXT NOT NULL,
    sub_concept TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '',
    skill TEXT NOT NULL DEFAULT '',
    dok_level INTEGER NOT NULL,
    question_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    origin TEXT NOT NULL DEFAULT 'ai',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT questions_dok_level_chk CHECK (dok_level BETWEEN 1 AND 4),
    CONSTRAINT questions_status_chk CHECK (status IN ('pending', 'approved', 'rejected')),
    CONSTRAINT questions_origin_chk CHECK (origin IN ('ai', 'teacher'))
);

CREATE INDEX IF NOT EXISTS questions_bank_lookup
    ON question_engine.questions (chapter_name, sub_concept, dok_level, question_type, status);

CREATE INDEX IF NOT EXISTS questions_topic_status
    ON question_engine.questions (topic_id, status);

CREATE INDEX IF NOT EXISTS questions_grade_created
    ON question_engine.questions (grade, created_at DESC);

CREATE TABLE IF NOT EXISTS question_engine.analytics_events (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    topic_id TEXT NOT NULL DEFAULT '',
    is_correct BOOLEAN NOT NULL,
    question_id TEXT NOT NULL,
    question_type TEXT NOT NULL,
    similarity_score DOUBLE PRECISION,
    distractor_tag TEXT,
    distractor_label TEXT,
    session_id TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT analytics_distractor_tag_chk
        CHECK (distractor_tag IS NULL OR distractor_tag IN ('NEAR_MISS', 'MISCONCEPTION', 'COMPLETE_MISS'))
);

CREATE INDEX IF NOT EXISTS analytics_events_user_topic
    ON question_engine.analytics_events (user_id, topic_id, created_at DESC);

ALTER TABLE question_engine.analytics_events
    ADD COLUMN IF NOT EXISTS error_category TEXT;
ALTER TABLE question_engine.analytics_events
    ADD COLUMN IF NOT EXISTS missing_keywords JSONB;
ALTER TABLE question_engine.analytics_events
    ADD COLUMN IF NOT EXISTS detailed_explanation TEXT;
ALTER TABLE question_engine.analytics_events
    ADD COLUMN IF NOT EXISTS missed_blanks JSONB;
ALTER TABLE question_engine.analytics_events
    ADD COLUMN IF NOT EXISTS concept_explanation TEXT;

CREATE TABLE IF NOT EXISTS question_engine.users (
    user_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE question_engine.users
    ADD COLUMN IF NOT EXISTS grade INTEGER;
ALTER TABLE question_engine.users
    ADD COLUMN IF NOT EXISTS completed_chapters_count INTEGER;
ALTER TABLE question_engine.users
    ADD COLUMN IF NOT EXISTS past_grade_marks_range TEXT;
ALTER TABLE question_engine.users
    ADD COLUMN IF NOT EXISTS placement_category TEXT;
ALTER TABLE question_engine.users
    ADD COLUMN IF NOT EXISTS placement_score DOUBLE PRECISION;
ALTER TABLE question_engine.users
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS question_engine.placement_evaluations (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES question_engine.users (user_id),
    grade INTEGER NOT NULL,
    completed_chapters_count INTEGER NOT NULL DEFAULT 0,
    past_grade_marks_range TEXT NOT NULL,
    quiz_correct INTEGER NOT NULL,
    quiz_total INTEGER NOT NULL DEFAULT 10,
    quiz_score DOUBLE PRECISION NOT NULL,
    past_score DOUBLE PRECISION NOT NULL,
    weighted_score DOUBLE PRECISION NOT NULL,
    category TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT placement_eval_marks_chk
        CHECK (past_grade_marks_range IN ('BELOW_50', '50_75', 'ABOVE_75')),
    CONSTRAINT placement_eval_category_chk
        CHECK (category IN ('WEAK', 'AVERAGE', 'ADVANCED')),
    CONSTRAINT placement_eval_grade_chk CHECK (grade BETWEEN 6 AND 9)
);

CREATE INDEX IF NOT EXISTS placement_evaluations_user
    ON question_engine.placement_evaluations (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS question_engine.assessment_sessions (
    session_id UUID PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES question_engine.users (user_id),
    grade INTEGER,
    topic_id TEXT,
    scope_chapter TEXT NOT NULL,
    used_question_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    asked_signatures JSONB NOT NULL DEFAULT '[]'::jsonb,
    history JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_state JSONB,
    last_action JSONB,
    questions_asked INTEGER NOT NULL DEFAULT 0,
    max_questions INTEGER NOT NULL DEFAULT 5,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS assessment_sessions_user
    ON question_engine.assessment_sessions (user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS question_engine.served_questions (
    user_id TEXT NOT NULL REFERENCES question_engine.users (user_id),
    question_id TEXT NOT NULL,
    session_id UUID,
    topic_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'bank',
    served_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, question_id),
    CONSTRAINT served_questions_source_chk CHECK (source IN ('bank', 'past_paper'))
);

CREATE INDEX IF NOT EXISTS served_questions_session
    ON question_engine.served_questions (session_id);

CREATE TABLE IF NOT EXISTS question_engine.attempts (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES question_engine.users (user_id),
    session_id UUID NOT NULL REFERENCES question_engine.assessment_sessions (session_id),
    question_id TEXT NOT NULL,
    topic_id TEXT NOT NULL DEFAULT '',
    is_correct BOOLEAN NOT NULL,
    accuracy_score DOUBLE PRECISION NOT NULL,
    similarity_score DOUBLE PRECISION,
    distractor_tag TEXT,
    student_answer TEXT NOT NULL DEFAULT '',
    trace JSONB NOT NULL DEFAULT '{}'::jsonb,
    answered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS attempts_session
    ON question_engine.attempts (session_id, answered_at);

CREATE INDEX IF NOT EXISTS attempts_user_topic
    ON question_engine.attempts (user_id, topic_id, answered_at DESC);

ALTER TABLE question_engine.attempts
    ADD COLUMN IF NOT EXISTS error_category TEXT;
ALTER TABLE question_engine.attempts
    ADD COLUMN IF NOT EXISTS missing_keywords JSONB;
ALTER TABLE question_engine.attempts
    ADD COLUMN IF NOT EXISTS detailed_explanation TEXT;
ALTER TABLE question_engine.attempts
    ADD COLUMN IF NOT EXISTS missed_blanks JSONB;
ALTER TABLE question_engine.attempts
    ADD COLUMN IF NOT EXISTS concept_explanation TEXT;
ALTER TABLE question_engine.attempts
    ADD COLUMN IF NOT EXISTS distractor_label TEXT;

-- Placeholder: no writers yet. Future frustration / affective signals.
CREATE TABLE IF NOT EXISTS question_engine.frustration_cues (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES question_engine.users (user_id),
    session_id UUID REFERENCES question_engine.assessment_sessions (session_id),
    cue_type TEXT NOT NULL,
    cue_value JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Placeholder: no BKT updates yet.
CREATE TABLE IF NOT EXISTS question_engine.bkt_mastery (
    user_id TEXT NOT NULL REFERENCES question_engine.users (user_id),
    topic_id TEXT NOT NULL,
    p_l DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    p_t DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    p_g DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    p_s DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, topic_id)
);

-- Placeholder: past-paper ingest/serving is not implemented.
CREATE TABLE IF NOT EXISTS question_engine.past_paper_items (
    item_id UUID PRIMARY KEY,
    grade INTEGER,
    topic_id TEXT,
    year INTEGER,
    paper_code TEXT,
    prompt TEXT,
    marking_scheme JSONB NOT NULL DEFAULT '{}'::jsonb
);
