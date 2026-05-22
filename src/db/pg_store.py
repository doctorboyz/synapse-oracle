"""PostgreSQL store — CRUD, FTS search, supersession, concepts, trace."""

import hashlib
import json
import uuid
from typing import Optional

import asyncpg

from src.config import Settings


class PgStore:
    """Async PostgreSQL knowledge store with tsvector full-text search."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or Settings()
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._settings.database_url, min_size=2, max_size=10, init=_init_jsonb
        )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def init_schema(self) -> None:
        """Ensure schema exists. Idempotent — safe to run on every startup."""
        schema_path = __file__.replace("pg_store.py", "schema.sql")
        with open(schema_path) as f:
            sql = f.read()
        async with self._pool.acquire() as conn:
            await conn.execute(sql)

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PgStore not connected — call connect() first")
        return self._pool

    # --- CRUD ---

    async def add(
        self,
        title: str,
        content: str,
        scope: str = "shared",
        doc_type: str = "learning",
        source_file: str | None = None,
        source_type: str = "manual",
        source_project: str | None = None,
        oracle_name: str | None = None,
        brain_path: str | None = None,
        brain_tier: str | None = None,
        concepts: list[str] | None = None,
        tags: list[str] | None = None,
        summary: str | None = None,
    ) -> dict:
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        concepts_list = _ensure_list(concepts)
        tags_list = _ensure_list(tags)

        async with self.pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM knowledge_documents WHERE content_hash = $1 AND scope = $2",
                content_hash, scope,
            )
            if existing:
                return {"id": str(existing["id"]), "scope": scope, "status": "duplicate"}

            row = await conn.fetchrow(
                """INSERT INTO knowledge_documents
                   (title, content, content_hash, scope, doc_type, source_file,
                    source_type, source_project, oracle_name, brain_path,
                    brain_tier, concepts, tags, summary)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                   RETURNING id""",
                title, content, content_hash, scope, doc_type, source_file,
                source_type, source_project, oracle_name, brain_path,
                brain_tier, concepts_list, tags_list, summary,
            )
            doc_id = str(row["id"])

            await conn.execute(
                """INSERT INTO scope_registry (name, doc_count)
                   VALUES ($1, 1)
                   ON CONFLICT (name) DO UPDATE SET doc_count = scope_registry.doc_count + 1""",
                scope,
            )

            if concepts_list:
                for concept in concepts_list:
                    await conn.execute(
                        """INSERT INTO concepts (name) VALUES ($1) ON CONFLICT (name) DO NOTHING""",
                        concept,
                    )
                    concept_row = await conn.fetchrow(
                        "SELECT id FROM concepts WHERE name = $1", concept
                    )
                    await conn.execute(
                        """INSERT INTO document_concepts (doc_id, concept_id)
                           VALUES ($1, $2) ON CONFLICT DO NOTHING""",
                        row["id"], concept_row["id"],
                    )

        return {"id": doc_id, "scope": scope, "status": "indexed"}

    async def get(self, doc_id: str, include_chain: bool = False) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM knowledge_documents WHERE id = $1", uuid.UUID(doc_id)
            )
            if not row:
                return None

            doc = _row_to_dict(row)

            if include_chain and doc.get("superseded_by"):
                chain = []
                current = doc["superseded_by"]
                while current:
                    next_row = await conn.fetchrow(
                        "SELECT id, title, created_at FROM knowledge_documents WHERE id = $1",
                        uuid.UUID(current),
                    )
                    if next_row:
                        chain.append({"id": str(next_row["id"]), "title": next_row["title"],
                                      "created_at": str(next_row["created_at"])})
                        current = None
                    else:
                        break
                doc["supersession_chain"] = chain

            return doc

    async def supersede(self, old_id: str, new_content: str, reason: str = "updated",
                        new_title: str | None = None) -> dict:
        async with self.pool.acquire() as conn:
            old_row = await conn.fetchrow(
                "SELECT * FROM knowledge_documents WHERE id = $1 AND superseded_by IS NULL",
                uuid.UUID(old_id),
            )
            if not old_row:
                raise ValueError(f"Document {old_id} not found or already superseded")

            title = new_title or old_row["title"]
            content_hash = hashlib.sha256(new_content.encode()).hexdigest()[:16]

            new_row = await conn.fetchrow(
                """INSERT INTO knowledge_documents
                   (title, content, content_hash, scope, doc_type, source_file,
                    source_type, source_project, oracle_name, brain_path,
                    brain_tier, concepts, tags, summary)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                   RETURNING id""",
                title, new_content, content_hash,
                old_row["scope"], old_row["doc_type"], old_row["source_file"],
                old_row["source_type"], old_row["source_project"],
                old_row["oracle_name"], old_row["brain_path"],
                old_row["brain_tier"], _ensure_list(old_row["concepts"]), _ensure_list(old_row["tags"]),
                old_row.get("summary"),
            )

            await conn.execute(
                "UPDATE knowledge_documents SET superseded_by = $1, updated_at = NOW() WHERE id = $2",
                new_row["id"], uuid.UUID(old_id),
            )

            await conn.execute(
                """INSERT INTO supersede_log (old_id, new_id, reason) VALUES ($1, $2, $3)""",
                uuid.UUID(old_id), new_row["id"], reason,
            )

        return {"id": str(new_row["id"]), "superseded": old_id, "status": "superseded"}

    # --- Search ---

    async def search_fts(
        self,
        query: str,
        scope: str | None = None,
        doc_type: str | None = None,
        oracle: str | None = None,
        source_project: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        ts_query = " | ".join(query.split())
        conditions = ["superseded_by IS NULL", "search_vector @@ to_tsquery('english', $1)"]
        params: list = [ts_query]
        idx = 2

        if scope:
            conditions.append(f"scope = ${idx}")
            params.append(scope)
            idx += 1
        if doc_type:
            conditions.append(f"doc_type = ${idx}")
            params.append(doc_type)
            idx += 1
        if oracle:
            conditions.append(f"oracle_name = ${idx}")
            params.append(oracle)
            idx += 1
        if source_project:
            conditions.append(f"source_project = ${idx}")
            params.append(source_project)
            idx += 1

        params.append(limit)
        where = " AND ".join(conditions)

        sql = f"""SELECT id, title, scope, doc_type, oracle_name, source_project,
                         ts_rank(search_vector, to_tsquery('english', $1)) AS rank
                  FROM knowledge_documents
                  WHERE {where}
                  ORDER BY rank DESC
                  LIMIT ${idx}"""

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "scope": r["scope"],
                "doc_type": r["doc_type"],
                "oracle_name": r["oracle_name"],
                "source_project": r["source_project"],
                "score": float(r["rank"]),
            }
            for r in rows
        ]

    # --- Concepts ---

    async def list_concepts(self, search: str | None = None, limit: int = 50) -> list[dict]:
        async with self.pool.acquire() as conn:
            if search:
                rows = await conn.fetch(
                    """SELECT c.name, c.description, COUNT(dc.doc_id) AS doc_count
                       FROM concepts c
                       LEFT JOIN document_concepts dc ON dc.concept_id = c.id
                       LEFT JOIN knowledge_documents kd ON kd.id = dc.doc_id AND kd.superseded_by IS NULL
                       WHERE c.name ILIKE $1
                       GROUP BY c.name, c.description
                       ORDER BY doc_count DESC LIMIT $2""",
                    f"%{search}%", limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT c.name, c.description, COUNT(dc.doc_id) AS doc_count
                       FROM concepts c
                       LEFT JOIN document_concepts dc ON dc.concept_id = c.id
                       LEFT JOIN knowledge_documents kd ON kd.id = dc.doc_id AND kd.superseded_by IS NULL
                       GROUP BY c.name, c.description
                       ORDER BY doc_count DESC LIMIT $1""",
                    limit,
                )
        return [{"name": r["name"], "description": r["description"],
                 "doc_count": r["doc_count"]} for r in rows]

    # --- Trace ---

    async def add_trace(
        self, source_id: str, target_id: str, relation: str, confidence: float = 1.0
    ) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO trace (source_id, target_id, relation, confidence)
                   VALUES ($1, $2, $3, $4) RETURNING id""",
                uuid.UUID(source_id), uuid.UUID(target_id), relation, confidence,
            )
        return {"id": str(row["id"]), "source_id": source_id,
                "target_id": target_id, "relation": relation}

    async def get_trace_chain(
        self, doc_id: str, direction: str = "both", max_depth: int = 5,
        relation: str | None = None,
    ) -> list[dict]:
        results = []
        async with self.pool.acquire() as conn:
            if direction in ("upstream", "both"):
                rows = await self._trace_walk(conn, doc_id, "target_id", "source_id",
                                              relation, max_depth)
                results.extend(rows)
            if direction in ("downstream", "both"):
                rows = await self._trace_walk(conn, doc_id, "source_id", "target_id",
                                              relation, max_depth)
                results.extend(rows)
        return results

    async def _trace_walk(
        self, conn, start_id: str, match_col: str, follow_col: str,
        relation: str | None, max_depth: int,
    ) -> list[dict]:
        results = []
        visited = {start_id}
        current_ids = [start_id]

        for depth in range(max_depth):
            if not current_ids:
                break

            rel_filter = f" AND t.relation = '{relation}'" if relation else ""
            placeholders = ", ".join(f"${i+1}" for i in range(len(current_ids)))
            sql = f"""SELECT t.source_id, t.target_id, t.relation, t.confidence,
                             kd.id, kd.title, kd.doc_type
                      FROM trace t
                      JOIN knowledge_documents kd ON kd.id = t.{follow_col}
                      WHERE t.{match_col} IN ({placeholders}){rel_filter}
                        AND kd.superseded_by IS NULL"""
            rows = await conn.fetch(sql, *[uuid.UUID(cid) for cid in current_ids])

            next_ids = []
            for r in rows:
                follow_id = str(r[follow_col])
                if follow_id not in visited:
                    visited.add(follow_id)
                    next_ids.append(follow_id)
                    results.append({
                        "id": str(r["id"]),
                        "title": r["title"],
                        "doc_type": r["doc_type"],
                        "relation": r["relation"],
                        "confidence": r["confidence"],
                        "depth": depth + 1,
                    })
            current_ids = next_ids

        return results

    # --- Scope & Stats ---

    async def list_scopes(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name, description, doc_count, oracle_name FROM scope_registry ORDER BY name"
            )
        return [dict(r) for r in rows]

    async def stats(self) -> dict:
        async with self.pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT count(*) FROM knowledge_documents WHERE superseded_by IS NULL"
            )
            by_type = await conn.fetch(
                """SELECT doc_type, count(*) AS cnt FROM knowledge_documents
                   WHERE superseded_by IS NULL GROUP BY doc_type ORDER BY cnt DESC"""
            )
            by_scope = await conn.fetch(
                """SELECT scope, count(*) AS cnt FROM knowledge_documents
                   WHERE superseded_by IS NULL GROUP BY scope ORDER BY cnt DESC"""
            )
            by_oracle = await conn.fetch(
                """SELECT oracle_name, count(*) AS cnt FROM knowledge_documents
                   WHERE superseded_by IS NULL AND oracle_name IS NOT NULL
                   GROUP BY oracle_name ORDER BY cnt DESC"""
            )
        return {
            "total_documents": total,
            "by_type": {r["doc_type"]: r["cnt"] for r in by_type},
            "by_scope": {r["scope"]: r["cnt"] for r in by_scope},
            "by_oracle": {r["oracle_name"]: r["cnt"] for r in by_oracle},
        }

    async def list_docs(
        self,
        scope: str | None = None,
        doc_type: str | None = None,
        oracle: str | None = None,
        limit: int = 20,
        offset: int = 0,
        order: str = "newest",
    ) -> list[dict]:
        conditions = ["superseded_by IS NULL"]
        params: list = []
        idx = 1

        if scope:
            conditions.append(f"scope = ${idx}")
            params.append(scope)
            idx += 1
        if doc_type:
            conditions.append(f"doc_type = ${idx}")
            params.append(doc_type)
            idx += 1
        if oracle:
            conditions.append(f"oracle_name = ${idx}")
            params.append(oracle)
            idx += 1

        params.append(limit)
        params.append(offset)
        where = " AND ".join(conditions)
        direction = "DESC" if order == "newest" else "ASC"

        sql = f"""SELECT id, title, scope, doc_type, oracle_name, source_project, created_at,
                         LEFT(content, 500) as content, summary
                  FROM knowledge_documents
                  WHERE {where}
                  ORDER BY created_at {direction}
                  LIMIT ${idx} OFFSET ${idx+1}"""

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [
            {
                "id": str(r["id"]), "title": r["title"], "scope": r["scope"],
                "doc_type": r["doc_type"], "oracle_name": r["oracle_name"],
                "source_project": r["source_project"],
                "created_at": str(r["created_at"]),
                "content": r["content"] or "",
                "summary": r["summary"] or "",
            }
            for r in rows
        ]


    # --- Search Topics ---

    async def add_search_topic(self, scope: str, topic: str, source: str = "web",
                               frequency: str = "daily") -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO search_topics (scope, topic, source, frequency)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (scope, topic, source) DO UPDATE
                   SET enabled = true, frequency = $4, last_searched = NULL
                   RETURNING id, enabled""",
                scope, topic, source, frequency,
            )
        return {"id": str(row["id"]), "scope": scope, "topic": topic, "source": source,
                "enabled": row["enabled"], "status": "created"}

    async def remove_search_topic(self, topic_id: str) -> dict:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM search_topics WHERE id = $1", uuid.UUID(topic_id)
            )
        deleted = "DELETE 1" in result
        return {"id": topic_id, "status": "deleted" if deleted else "not_found"}

    async def list_search_topics(self, scope: str | None = None,
                                  enabled_only: bool = False) -> list[dict]:
        conditions = []
        params: list = []
        idx = 1

        if scope:
            conditions.append(f"scope = ${idx}")
            params.append(scope)
            idx += 1
        if enabled_only:
            conditions.append("enabled = true")

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""SELECT id, scope, topic, source, frequency, enabled, last_searched, created_at
                  FROM search_topics WHERE {where} ORDER BY scope, topic"""

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [
            {
                "id": str(r["id"]), "scope": r["scope"], "topic": r["topic"],
                "source": r["source"], "frequency": r["frequency"],
                "enabled": r["enabled"], "last_searched": str(r["last_searched"]) if r["last_searched"] else None,
                "created_at": str(r["created_at"]),
            }
            for r in rows
        ]

    async def update_search_topic_last_searched(self, topic_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE search_topics SET last_searched = NOW() WHERE id = $1",
                uuid.UUID(topic_id),
            )

    async def toggle_search_topic(self, topic_id: str, enabled: bool) -> dict:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE search_topics SET enabled = $1 WHERE id = $2",
                enabled, uuid.UUID(topic_id),
            )
        updated = "UPDATE 1" in result
        return {"id": topic_id, "enabled": enabled, "status": "updated" if updated else "not_found"}

    async def find_by_source_file(self, source_file: str, scope: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, source_file FROM knowledge_documents
                   WHERE source_file = $1 AND scope = $2 AND superseded_by IS NULL
                   LIMIT 1""",
                source_file, scope,
            )
        if row:
            return {"id": str(row["id"]), "source_file": row["source_file"]}
        return None


    # --- Reconcile Log ---

    async def start_reconcile_log(self, scope: str | None = None, dry_run: bool = False) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO reconcile_log (scope, dry_run, status)
                   VALUES ($1, $2, 'running')
                   RETURNING id, started_at""",
                scope, dry_run,
            )
        return {"id": str(row["id"]), "started_at": str(row["started_at"])}

    async def complete_reconcile_log(
        self,
        log_id: str,
        merged_duplicates: int = 0,
        removed_duplicates: int = 0,
        conflicts_found: int = 0,
        conflicts_resolved: int = 0,
        status: str = "completed",
        error_message: str | None = None,
    ) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE reconcile_log
                   SET completed_at = NOW(),
                       merged_duplicates = $2,
                       removed_duplicates = $3,
                       conflicts_found = $4,
                       conflicts_resolved = $5,
                       status = $6,
                       error_message = $7
                   WHERE id = $1
                   RETURNING completed_at""",
                uuid.UUID(log_id), merged_duplicates, removed_duplicates,
                conflicts_found, conflicts_resolved, status, error_message,
            )
        return {"id": log_id, "status": status, "completed_at": str(row["completed_at"]) if row else None}

    async def list_reconcile_log(self, limit: int = 20) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, started_at, completed_at, scope, dry_run,
                          merged_duplicates, removed_duplicates,
                          conflicts_found, conflicts_resolved,
                          status, error_message
                   FROM reconcile_log
                   ORDER BY started_at DESC
                   LIMIT $1""",
                limit,
            )
        return [
            {
                "id": str(r["id"]),
                "started_at": str(r["started_at"]),
                "completed_at": str(r["completed_at"]) if r["completed_at"] else None,
                "scope": r["scope"],
                "dry_run": r["dry_run"],
                "merged_duplicates": r["merged_duplicates"],
                "removed_duplicates": r["removed_duplicates"],
                "conflicts_found": r["conflicts_found"],
                "conflicts_resolved": r["conflicts_resolved"],
                "status": r["status"],
                "error_message": r["error_message"],
            }
            for r in rows
        ]


    # --- Pending Reviews (LINE confirmation flow) ---

    async def create_pending_review(self, review: dict) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO pending_reviews
                   (title, content, summary, scope, doc_type, source_type, source_project,
                    oracle_name, tags, concepts, metadata, reply_token, user_id, chat_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                           $9, $10, $11, $12, $13, $14)
                   RETURNING id, created_at""",
                review["title"], review["content"], review.get("summary"),
                review.get("scope", "shared"), review.get("doc_type", "note"),
                review.get("source_type", "line"), review.get("source_project"),
                review.get("oracle_name"), _ensure_list(review.get("tags")),
                _ensure_list(review.get("concepts")), review.get("metadata", {}),
                review.get("reply_token"), review.get("user_id"), review.get("chat_id"),
            )
        return {"id": str(row["id"]), "created_at": str(row["created_at"])}

    async def get_pending_review_for_user(self, user_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, title, content, summary, scope, doc_type, tags, concepts, metadata
                   FROM pending_reviews
                   WHERE user_id = $1 AND status = 'pending' AND expires_at > NOW()
                   ORDER BY created_at DESC
                   LIMIT 1""",
                user_id,
            )
        if row:
            return _row_to_dict(row)
        return None

    async def get_pending_review_for_chat(self, chat_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, title, content, summary, scope, doc_type, tags, concepts, metadata
                   FROM pending_reviews
                   WHERE chat_id = $1 AND status = 'pending' AND expires_at > NOW()
                   ORDER BY created_at DESC
                   LIMIT 1""",
                chat_id,
            )
        if row:
            return _row_to_dict(row)
        return None

    async def confirm_pending_review(self, review_id: str) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE pending_reviews
                   SET status = 'confirmed'
                   WHERE id = $1 AND status = 'pending'
                   RETURNING title, content, summary, scope, doc_type, source_type,
                             source_project, oracle_name, tags, concepts, metadata""",
                uuid.UUID(review_id),
            )
        if not row:
            return {"status": "not_found"}
        return {
            "status": "confirmed",
            "title": row["title"],
            "content": row["content"],
            "summary": row["summary"],
            "scope": row["scope"],
            "doc_type": row["doc_type"],
            "source_type": row["source_type"],
            "source_project": row["source_project"],
            "oracle_name": row["oracle_name"],
            "tags": row["tags"],
            "concepts": row["concepts"],
            "metadata": row["metadata"],
        }

    async def cancel_pending_review(self, review_id: str) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE pending_reviews
                   SET status = 'cancelled'
                   WHERE id = $1 AND status = 'pending'
                   RETURNING id""",
                uuid.UUID(review_id),
            )
        if not row:
            return {"status": "not_found"}
        return {"status": "cancelled", "id": str(row["id"])}

    async def expire_pending_reviews(self) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE pending_reviews
                   SET status = 'expired'
                   WHERE status = 'pending' AND expires_at <= NOW()"""
            )
        # Parse "UPDATE N" result
        parts = result.split()
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0


    # --- Cleanup (for tests) ---

    async def clean_pending_reviews(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM pending_reviews")


async def _init_jsonb(conn: asyncpg.Connection) -> None:
    """Register jsonb codec so asyncpg deserializes to native Python objects."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


def _ensure_list(val) -> list:
    """Ensure value is a list. Handles JSON strings, single strings, None."""
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return [val]
    return []


def _row_to_dict(row: asyncpg.Record) -> dict:
    d = {}
    for key in row.keys():
        val = row[key]
        if isinstance(val, uuid.UUID):
            val = str(val)
        d[key] = val
    return d