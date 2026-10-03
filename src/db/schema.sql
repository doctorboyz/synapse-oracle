-- synapse PostgreSQL schema (idempotent — safe to run on every startup)

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- Migration: copy tags from JSONB column to junction tables, then drop JSONB column
DO $$
DECLARE
    rec RECORD;
    tag_name TEXT;
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'knowledge_documents' AND column_name = 'tags'
    ) THEN
        FOR rec IN
            SELECT id, tags FROM knowledge_documents WHERE tags IS NOT NULL AND jsonb_array_length(tags) > 0
        LOOP
            FOR tag_name IN SELECT jsonb_array_elements_text(rec.tags)
            LOOP
                INSERT INTO tags (name) VALUES (tag_name) ON CONFLICT (name) DO NOTHING;
                INSERT INTO document_tags (doc_id, tag_id)
                SELECT rec.id, t.id FROM tags t WHERE t.name = tag_name
                ON CONFLICT DO NOTHING;
            END LOOP;
        END LOOP;
        ALTER TABLE knowledge_documents DROP COLUMN tags;
    END IF;
END $$;

-- Migration: add metadata JSONB and archived_at columns (v5 prep)
ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- Migration: update doc_type default from 'learning' to 'note'
ALTER TABLE knowledge_documents ALTER COLUMN doc_type SET DEFAULT 'note';

-- Migration: scope is being deprecated in favor of source_project + tags; drop NOT NULL
ALTER TABLE knowledge_documents ALTER COLUMN scope DROP NOT NULL;
ALTER TABLE knowledge_documents ALTER COLUMN scope SET DEFAULT NULL;

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    doc_type        TEXT NOT NULL DEFAULT 'note',
    scope           TEXT,
    source_file     TEXT,
    source_type     TEXT NOT NULL DEFAULT 'manual',
    source_project  TEXT,
    oracle_name     TEXT,
    brain_path      TEXT,
    brain_tier      TEXT,
    concepts        JSONB DEFAULT '[]',
    superseded_by   UUID REFERENCES knowledge_documents(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ,
    search_vector   tsvector,
    embedding       vector(768),                -- pgvector replaces Qdrant
    summary         TEXT                        -- auto-summarization
);

-- Drop old dedup constraint — dedup is now async via defrag
ALTER TABLE knowledge_documents DROP CONSTRAINT IF EXISTS knowledge_documents_content_hash_scope_key;

-- Trigger to auto-update search_vector from title, content, concepts
-- Uses 'simple' dictionary to support Thai + mixed-language content
CREATE OR REPLACE FUNCTION update_search_vector() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('simple', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.content, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(
            (SELECT string_agg(value::text, ' ') FROM jsonb_array_elements_text(NEW.concepts) AS value), ''
        )), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

DROP TRIGGER IF EXISTS trg_search_vector ON knowledge_documents;
CREATE TRIGGER trg_search_vector
    BEFORE INSERT OR UPDATE ON knowledge_documents
    FOR EACH ROW EXECUTE FUNCTION update_search_vector();

CREATE INDEX IF NOT EXISTS idx_doc_search ON knowledge_documents USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_doc_scope ON knowledge_documents(scope) WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS idx_doc_type ON knowledge_documents(doc_type) WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS idx_doc_oracle ON knowledge_documents(oracle_name) WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS idx_doc_hash ON knowledge_documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_doc_brain_tier ON knowledge_documents(brain_tier) WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS idx_doc_source_project ON knowledge_documents(source_project) WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS idx_doc_created ON knowledge_documents(created_at DESC) WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS idx_doc_source_type ON knowledge_documents(source_type);
CREATE INDEX IF NOT EXISTS idx_doc_metadata ON knowledge_documents USING GIN(metadata);
CREATE INDEX IF NOT EXISTS idx_doc_archived ON knowledge_documents(archived_at) WHERE archived_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_doc_active ON knowledge_documents(created_at DESC) WHERE superseded_by IS NULL AND archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_doc_embedding ON knowledge_documents USING ivfflat (embedding vector_cosine_ops) WHERE embedding IS NOT NULL;

CREATE TABLE IF NOT EXISTS supersede_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    old_id      UUID NOT NULL REFERENCES knowledge_documents(id),
    new_id      UUID NOT NULL REFERENCES knowledge_documents(id),
    reason      TEXT DEFAULT 'updated',
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scope_registry (
    name        TEXT PRIMARY KEY,
    description TEXT,
    doc_count   INTEGER DEFAULT 0,
    oracle_name TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS concepts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_concepts (
    doc_id      UUID REFERENCES knowledge_documents(id),
    concept_id  UUID REFERENCES concepts(id),
    PRIMARY KEY (doc_id, concept_id)
);

CREATE INDEX IF NOT EXISTS idx_dc_doc ON document_concepts(doc_id);
CREATE INDEX IF NOT EXISTS idx_dc_concept ON document_concepts(concept_id);

-- Tags — many-to-many document classification (replaces scope for content-based filtering)
CREATE TABLE IF NOT EXISTS tags (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_tags (
    doc_id      UUID REFERENCES knowledge_documents(id),
    tag_id      UUID REFERENCES tags(id),
    PRIMARY KEY (doc_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_dt_doc ON document_tags(doc_id);
CREATE INDEX IF NOT EXISTS idx_dt_tag ON document_tags(tag_id);

CREATE TABLE IF NOT EXISTS trace (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id   UUID REFERENCES knowledge_documents(id),
    target_id   UUID REFERENCES knowledge_documents(id),
    relation    TEXT NOT NULL,
    confidence  REAL DEFAULT 1.0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trace_source ON trace(source_id);
CREATE INDEX IF NOT EXISTS idx_trace_target ON trace(target_id);

-- Project registry for cross-project search
CREATE TABLE IF NOT EXISTS registered_projects (
    scope           TEXT PRIMARY KEY,
    project_path    TEXT NOT NULL,
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Search topics per scope — web/social monitoring
CREATE TABLE IF NOT EXISTS search_topics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope           TEXT NOT NULL,
    topic           TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'web',  -- web, twitter, reddit, hn, youtube
    frequency       TEXT NOT NULL DEFAULT 'daily', -- hourly, daily, weekly
    last_searched   TIMESTAMPTZ,
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(scope, topic, source)
);
CREATE INDEX IF NOT EXISTS idx_search_topic_scope ON search_topics(scope);
CREATE INDEX IF NOT EXISTS idx_search_topic_enabled ON search_topics(enabled) WHERE enabled = true;

-- Reconcile log — persistent audit trail
CREATE TABLE IF NOT EXISTS reconcile_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    scope           TEXT,
    dry_run         BOOLEAN DEFAULT false,
    merged_duplicates   INTEGER DEFAULT 0,
    removed_duplicates  INTEGER DEFAULT 0,
    conflicts_found     INTEGER DEFAULT 0,
    conflicts_resolved  INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'running',  -- running, completed, failed
    error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_reconcile_log_started ON reconcile_log(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_reconcile_log_status ON reconcile_log(status);

-- Pending reviews — LINE confirmation flow
CREATE TABLE IF NOT EXISTS pending_reviews (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    summary         TEXT,
    scope           TEXT NOT NULL DEFAULT 'shared',
    doc_type        TEXT NOT NULL DEFAULT 'note',
    source_type     TEXT NOT NULL DEFAULT 'line',
    source_project  TEXT,
    oracle_name     TEXT,
    tags            JSONB DEFAULT '[]',
    concepts        JSONB DEFAULT '[]',
    metadata        JSONB DEFAULT '{}',
    reply_token     TEXT,
    user_id         TEXT,
    chat_id         TEXT,
    status          TEXT DEFAULT 'pending',  -- pending, confirmed, cancelled, expired
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '1 hour'
);
CREATE INDEX IF NOT EXISTS idx_pending_user ON pending_reviews(user_id, status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_pending_chat ON pending_reviews(chat_id, status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_pending_expires ON pending_reviews(expires_at);

-- =============================================================================
-- V4: DOCUMENT CHUNKS (break long documents into overlapping chunks)
-- =============================================================================

CREATE TABLE IF NOT EXISTS document_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          UUID NOT NULL REFERENCES knowledge_documents(id),
    chunk_index     INTEGER NOT NULL,
    content         TEXT NOT NULL,
    embedding       vector(768),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(doc_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON document_chunks(doc_id);

-- =============================================================================
-- V4: HYBRID SEARCH FUNCTION (FTS + pgvector in one SQL call)
-- =============================================================================

CREATE OR REPLACE FUNCTION hybrid_search(
    query_text      TEXT,
    query_embedding VECTOR(768),
    scope_filter    TEXT DEFAULT NULL,
    doc_type_filter TEXT DEFAULT NULL,
    tag_filter      TEXT[] DEFAULT NULL,
    result_limit    INTEGER DEFAULT 10
) RETURNS TABLE(
    id              UUID,
    title           TEXT,
    content         TEXT,
    scope           TEXT,
    doc_type        TEXT,
    oracle_name     TEXT,
    source_project  TEXT,
    tags            JSONB,
    concepts        JSONB,
    created_at      TIMESTAMPTZ,
    fts_score       FLOAT,
    vec_score       FLOAT,
    hybrid_score    FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        kd.id,
        kd.title,
        LEFT(kd.content, 500) AS content,
        kd.scope,
        kd.doc_type,
        kd.oracle_name,
        kd.source_project,
        COALESCE(
            (SELECT jsonb_agg(t.name) FROM document_tags dt JOIN tags t ON t.id = dt.tag_id WHERE dt.doc_id = kd.id),
            '[]'::jsonb
        ) AS tags,
        kd.concepts,
        kd.created_at,
        COALESCE(ts_rank_cd(kd.search_vector, to_tsquery('simple', query_text)), 0) AS fts_score,
        COALESCE(1 - (kd.embedding <=> query_embedding), 0) AS vec_score,
        COALESCE(ts_rank_cd(kd.search_vector, to_tsquery('simple', query_text)), 0) * 0.4 +
        COALESCE(1 - (kd.embedding <=> query_embedding), 0) * 0.6 AS hybrid_score
    FROM knowledge_documents kd
    WHERE kd.superseded_by IS NULL
      AND (
          kd.search_vector @@ to_tsquery('simple', query_text)
          OR kd.embedding IS NOT NULL
      )
      AND (scope_filter IS NULL OR kd.scope = scope_filter)
      AND (doc_type_filter IS NULL OR kd.doc_type = doc_type_filter)
      AND (tag_filter IS NULL OR EXISTS (
          SELECT 1 FROM document_tags dt
          JOIN tags t ON t.id = dt.tag_id
          WHERE dt.doc_id = kd.id AND t.name = ANY(tag_filter)
      ))
    ORDER BY hybrid_score DESC
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql STABLE;

-- =============================================================================
-- V4: TAG-BASED ASSISTANT INFRASTRUCTURE
-- =============================================================================

CREATE TABLE IF NOT EXISTS tag_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tag_name        TEXT NOT NULL UNIQUE,
    handler         TEXT NOT NULL,
    description     TEXT,
    auto_classify   BOOLEAN DEFAULT true,
    alert_on_due    BOOLEAN DEFAULT false,
    collect_related BOOLEAN DEFAULT false,
    schedule        TEXT,
    config          JSONB DEFAULT '{}',
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          UUID REFERENCES knowledge_documents(id),
    tag_name        TEXT NOT NULL,
    task_type       TEXT NOT NULL DEFAULT 'reminder',
    due_date        TIMESTAMPTZ,
    recurrence      TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    alert_before    INTERVAL DEFAULT '1 hour',
    last_alerted    TIMESTAMPTZ,
    notified_at     TIMESTAMPTZ[] DEFAULT ARRAY[]::TIMESTAMPTZ[],
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sched_task_due ON scheduled_tasks(due_date) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_sched_task_doc ON scheduled_tasks(doc_id);
CREATE INDEX IF NOT EXISTS idx_sched_task_tag ON scheduled_tasks(tag_name, status);

CREATE TABLE IF NOT EXISTS alert_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID REFERENCES scheduled_tasks(id),
    doc_id          UUID REFERENCES knowledge_documents(id),
    tag_name        TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT 'line',
    message         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'sent',
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alert_log_sent ON alert_log(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_log_task ON alert_log(task_id);

-- =============================================================================
-- V4: OBSIDIAN SYNC TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS obsidian_sync_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          UUID NOT NULL REFERENCES knowledge_documents(id),
    vault_path      TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    action          TEXT NOT NULL DEFAULT 'created',
    file_hash       TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_obsidian_doc ON obsidian_sync_log(doc_id);
CREATE INDEX IF NOT EXISTS idx_obsidian_synced ON obsidian_sync_log(synced_at DESC);