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
