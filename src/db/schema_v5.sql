-- synapse V5: Unified documents schema
-- Migrates knowledge_documents → documents with JSONB metadata + archived_at
-- Tags and concepts move from junction tables to JSONB (namespace tags)
-- brain_path, brain_tier, scope, source_file, summary → metadata JSONB
-- Adds event-based doc_types (todo, not-to-do, reminder, event, payment, deadline)
-- Adds content-based doc_types (idea, insight, moment, good-to-know)

-- ============================================================================
-- STEP 1: Create new documents table
-- ============================================================================

CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    doc_type        TEXT NOT NULL DEFAULT 'note',
    metadata        JSONB DEFAULT '{}',
    tags            JSONB DEFAULT '[]',
    concepts        JSONB DEFAULT '[]',
    source_type     TEXT NOT NULL DEFAULT 'manual',
    source_project  TEXT,
    oracle_name     TEXT,
    superseded_by   UUID REFERENCES documents(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ,
    archived_at     TIMESTAMPTZ,
    search_vector   tsvector,
    embedding       vector(768)
);

-- ============================================================================
-- STEP 2: Migrate data from knowledge_documents
-- ============================================================================

-- Only run if knowledge_documents exists and has data
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'knowledge_documents') THEN
        -- Migrate rows, converting old columns to metadata JSONB
        INSERT INTO documents (id, title, content, content_hash, doc_type, metadata, tags, concepts,
                               source_type, source_project, oracle_name, superseded_by,
                               created_at, updated_at, search_vector, embedding)
        SELECT
            kd.id,
            kd.title,
            kd.content,
            kd.content_hash,
            kd.doc_type,
            jsonb_strip_nulls(jsonb_build_object(
                'brain_path', kd.brain_path,
                'brain_tier', kd.brain_tier,
                'source_file', kd.source_file,
                'scope', kd.scope,
                'summary', kd.summary
            )),
            COALESCE(
                (SELECT jsonb_agg(t.name) FROM document_tags dt JOIN tags t ON t.id = dt.tag_id WHERE dt.doc_id = kd.id),
                '[]'::jsonb
            ),
            COALESCE(kd.concepts, '[]'::jsonb),
            kd.source_type,
            kd.source_project,
            kd.oracle_name,
            kd.superseded_by,
            kd.created_at,
            kd.updated_at,
            kd.search_vector,
            kd.embedding
        FROM knowledge_documents kd
        ON CONFLICT (id) DO NOTHING;

        -- Migrate supersede_log
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'supersede_log') THEN
            INSERT INTO supersede_log_v5 (id, old_id, new_id, reason, timestamp)
            SELECT id, old_id, new_id, reason, timestamp FROM supersede_log
            ON CONFLICT (id) DO NOTHING;
        END IF;

        -- Migrate document_chunks
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'document_chunks') THEN
            INSERT INTO document_chunks_v5 (id, doc_id, chunk_index, content, embedding, created_at)
            SELECT id, doc_id, chunk_index, content, embedding, created_at FROM document_chunks
            ON CONFLICT (id) DO NOTHING;
        END IF;

        -- Migrate scheduled_tasks
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'scheduled_tasks') THEN
            INSERT INTO scheduled_tasks_v5 (id, doc_id, tag_name, task_type, due_date, recurrence,
                                            status, alert_before, last_alerted, metadata, created_at)
            SELECT id, doc_id, tag_name, task_type, due_date, recurrence,
                   status, alert_before, last_alerted, metadata, created_at
            FROM scheduled_tasks
            ON CONFLICT (id) DO NOTHING;
        END IF;

        -- Migrate alert_log
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'alert_log') THEN
            INSERT INTO alert_log_v5 (id, task_id, doc_id, tag_name, channel, message, status, sent_at)
            SELECT id, task_id, doc_id, tag_name, channel, message, status, sent_at
            FROM alert_log
            ON CONFLICT (id) DO NOTHING;
        END IF;

        -- Migrate tag_rules
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tag_rules') THEN
            INSERT INTO tag_rules_v5 (id, tag_name, handler, description, auto_classify,
                                      alert_on_due, collect_related, schedule, config, enabled, created_at)
            SELECT id, tag_name, handler, description, auto_classify,
                   alert_on_due, collect_related, schedule, config, enabled, created_at
            FROM tag_rules
            ON CONFLICT (id) DO NOTHING;
        END IF;

        -- Migrate pending_reviews
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'pending_reviews') THEN
            INSERT INTO pending_reviews_v5 (id, title, content, summary, doc_type, source_type,
                                            source_project, oracle_name, tags, concepts, metadata,
                                            reply_token, user_id, chat_id, status, created_at, expires_at)
            SELECT id, title, content, summary, doc_type, source_type,
                   source_project, oracle_name, tags, concepts, metadata,
                   reply_token, user_id, chat_id, status, created_at, expires_at
            FROM pending_reviews
            ON CONFLICT (id) DO NOTHING;
        END IF;
    END IF;
END $$;

-- ============================================================================
-- STEP 3: Create new support tables (v5 versions)
-- ============================================================================

CREATE TABLE IF NOT EXISTS supersede_log_v5 (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    old_id      UUID NOT NULL REFERENCES documents(id),
    new_id      UUID NOT NULL REFERENCES documents(id),
    reason      TEXT DEFAULT 'updated',
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_chunks_v5 (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          UUID NOT NULL REFERENCES documents(id),
    chunk_index     INTEGER NOT NULL,
    content         TEXT NOT NULL,
    embedding       vector(768),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(doc_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunk_doc_v5 ON document_chunks_v5(doc_id);

CREATE TABLE IF NOT EXISTS trace_v5 (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id   UUID REFERENCES documents(id),
    target_id  UUID REFERENCES documents(id),
    relation   TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trace_source_v5 ON trace_v5(source_id);
CREATE INDEX IF NOT EXISTS idx_trace_target_v5 ON trace_v5(target_id);

CREATE TABLE IF NOT EXISTS registered_projects_v5 (
    scope           TEXT PRIMARY KEY,
    project_path    TEXT NOT NULL,
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS search_topics_v5 (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope           TEXT NOT NULL,
    topic           TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'web',
    frequency       TEXT NOT NULL DEFAULT 'daily',
    last_searched   TIMESTAMPTZ,
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(scope, topic, source)
);
CREATE INDEX IF NOT EXISTS idx_search_topic_scope_v5 ON search_topics_v5(scope);
CREATE INDEX IF NOT EXISTS idx_search_topic_enabled_v5 ON search_topics_v5(enabled) WHERE enabled = true;

CREATE TABLE IF NOT EXISTS reconcile_log_v5 (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    scope           TEXT,
    dry_run         BOOLEAN DEFAULT false,
    merged_duplicates   INTEGER DEFAULT 0,
    removed_duplicates  INTEGER DEFAULT 0,
    conflicts_found     INTEGER DEFAULT 0,
    conflicts_resolved  INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'running',
    error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_reconcile_log_started_v5 ON reconcile_log_v5(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_reconcile_log_status_v5 ON reconcile_log_v5(status);

CREATE TABLE IF NOT EXISTS pending_reviews_v5 (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    summary         TEXT,
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
    status          TEXT DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '1 hour'
);
CREATE INDEX IF NOT EXISTS idx_pending_user_v5 ON pending_reviews_v5(user_id, status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_pending_chat_v5 ON pending_reviews_v5(chat_id, status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_pending_expires_v5 ON pending_reviews_v5(expires_at);

CREATE TABLE IF NOT EXISTS tag_rules_v5 (
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

CREATE TABLE IF NOT EXISTS scheduled_tasks_v5 (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          UUID REFERENCES documents(id),
    tag_name        TEXT NOT NULL,
    task_type       TEXT NOT NULL DEFAULT 'reminder',
    due_date        TIMESTAMPTZ,
    recurrence      TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    alert_before    INTERVAL DEFAULT '1 hour',
    last_alerted    TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sched_task_due_v5 ON scheduled_tasks_v5(due_date) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_sched_task_doc_v5 ON scheduled_tasks_v5(doc_id);
CREATE INDEX IF NOT EXISTS idx_sched_task_tag_v5 ON scheduled_tasks_v5(tag_name, status);

CREATE TABLE IF NOT EXISTS alert_log_v5 (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID REFERENCES scheduled_tasks_v5(id),
    doc_id          UUID REFERENCES documents(id),
    tag_name        TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT 'line',
    message         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'sent',
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alert_log_sent_v5 ON alert_log_v5(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_log_task_v5 ON alert_log_v5(task_id);

CREATE TABLE IF NOT EXISTS obsidian_sync_log_v5 (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          UUID NOT NULL REFERENCES documents(id),
    vault_path      TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    action          TEXT NOT NULL DEFAULT 'created',
    file_hash       TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_obsidian_doc_v5 ON obsidian_sync_log_v5(doc_id);
CREATE INDEX IF NOT EXISTS idx_obsidian_synced_v5 ON obsidian_sync_log_v5(synced_at DESC);

-- ============================================================================
-- STEP 4: Indexes on documents
-- ============================================================================

-- Trigger: auto-update search_vector
CREATE OR REPLACE FUNCTION update_search_vector_v5() RETURNS trigger AS $$
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

DROP TRIGGER IF EXISTS trg_search_vector_v5 ON documents;
CREATE TRIGGER trg_search_vector_v5
    BEFORE INSERT OR UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_search_vector_v5();

CREATE INDEX IF NOT EXISTS idx_doc_search_v5 ON documents USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_doc_type_v5 ON documents(doc_type) WHERE superseded_by IS NULL AND archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_doc_active_v5 ON documents(created_at DESC) WHERE superseded_by IS NULL AND archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_doc_archived_v5 ON documents(archived_at) WHERE archived_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_doc_hash_v5 ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_doc_oracle_v5 ON documents(oracle_name) WHERE superseded_by IS NULL AND archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_doc_source_project_v5 ON documents(source_project) WHERE superseded_by IS NULL AND archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_doc_source_type_v5 ON documents(source_type);
CREATE INDEX IF NOT EXISTS idx_doc_embedding_v5 ON documents USING ivfflat (embedding vector_cosine_ops) WHERE embedding IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_doc_metadata_v5 ON documents USING GIN(metadata);
CREATE INDEX IF NOT EXISTS idx_doc_tags_v5 ON documents USING GIN(tags);

-- ============================================================================
-- STEP 5: Hybrid search function (v5 — uses JSONB tags instead of junction)
-- ============================================================================

CREATE OR REPLACE FUNCTION hybrid_search_v5(
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
    doc_type        TEXT,
    oracle_name     TEXT,
    source_project  TEXT,
    metadata        JSONB,
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
        d.id,
        d.title,
        LEFT(d.content, 500) AS content,
        d.doc_type,
        d.oracle_name,
        d.source_project,
        d.metadata,
        d.tags,
        d.concepts,
        d.created_at,
        COALESCE(ts_rank_cd(d.search_vector, to_tsquery('simple', query_text)), 0) AS fts_score,
        COALESCE(1 - (d.embedding <=> query_embedding), 0) AS vec_score,
        COALESCE(ts_rank_cd(d.search_vector, to_tsquery('simple', query_text)), 0) * 0.4 +
        COALESCE(1 - (d.embedding <=> query_embedding), 0) * 0.6 AS hybrid_score
    FROM documents d
    WHERE d.superseded_by IS NULL
      AND d.archived_at IS NULL
      AND (
          d.search_vector @@ to_tsquery('simple', query_text)
          OR d.embedding IS NOT NULL
      )
      AND (scope_filter IS NULL OR d.metadata->>'scope' = scope_filter
           OR d.source_project = scope_filter)
      AND (doc_type_filter IS NULL OR d.doc_type = doc_type_filter)
      AND (tag_filter IS NULL OR d.tags ?| tag_filter)
    ORDER BY hybrid_score DESC
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql STABLE;