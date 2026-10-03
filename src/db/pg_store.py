"""PostgreSQL store — CRUD, FTS search, vector search, supersession, concepts, trace."""

import hashlib
import json
import uuid

import asyncpg
from pgvector.asyncpg import register_vector

from src.config import Settings


class PgStore:
    """Async PostgreSQL knowledge store with tsvector full-text search."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or Settings()
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._settings.database_url, min_size=2, max_size=10, init=_init_codecs
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
        doc_type: str = "note",
        source_type: str = "manual",
        source_project: str | None = None,
        oracle_name: str | None = None,
        concepts: list[str] | None = None,
        tags: list[str] | None = None,
        metadata: dict | None = None,
        source_file: str | None = None,
        brain_path: str | None = None,
        brain_tier: str | None = None,
        summary: str | None = None,
        scope: str | None = None,
    ) -> dict:
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        concepts_json = _ensure_list(concepts)
        tags_list = _ensure_list(tags)

        # Build metadata JSONB from explicit metadata dict + legacy flat params
        # Flat params take priority for their specific columns; extras go into metadata
        doc_metadata = dict(metadata) if metadata else {}
        if brain_path:
            doc_metadata.setdefault("brain_path", brain_path)
        if brain_tier:
            doc_metadata.setdefault("brain_tier", brain_tier)
        if source_file:
            doc_metadata.setdefault("source_file", source_file)
        if summary:
            doc_metadata.setdefault("summary", summary)
        if scope:
            doc_metadata.setdefault("scope", scope)

        # Extract flat column values from metadata (for backward compat columns)
        flat_brain_path = doc_metadata.pop("brain_path", brain_path)
        flat_brain_tier = doc_metadata.pop("brain_tier", brain_tier)
        flat_source_file = doc_metadata.pop("source_file", source_file)
        flat_summary = doc_metadata.pop("summary", summary)
        flat_scope = doc_metadata.pop("scope", scope)

        async with self.pool.acquire() as conn:
            # Content hash dedup — exact match only
            existing = await conn.fetchrow(
                "SELECT id FROM knowledge_documents WHERE content_hash = $1",
                content_hash,
            )
            if existing:
                return {"id": str(existing["id"]), "status": "duplicate",
                        "tags": tags_list}

            row = await conn.fetchrow(
                """INSERT INTO knowledge_documents
                   (title, content, content_hash, doc_type, source_type,
                    source_project, oracle_name, brain_path, brain_tier,
                    source_file, scope, concepts, summary, metadata)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                   RETURNING id""",
                title, content, content_hash, doc_type, source_type,
                source_project, oracle_name, flat_brain_path, flat_brain_tier,
                flat_source_file, flat_scope,
                concepts_json if concepts_json else [],
                flat_summary,
                doc_metadata if doc_metadata else {},
            )
            doc_id = str(row["id"])

            # Sync tags to junction tables
            if tags_list:
                await self._sync_tags(conn, row["id"], tags_list)

            # Sync concepts to junction tables
            if concepts_json:
                await self._sync_concepts(conn, row["id"], concepts_json)

        return {"id": doc_id, "status": "indexed", "tags": tags_list}

    async def get(self, doc_id: str, include_chain: bool = False) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM knowledge_documents WHERE id = $1", uuid.UUID(doc_id)
            )
            if not row:
                return None

            doc = _row_to_dict(row)

            # Enrich tags from junction table
            tag_rows = await conn.fetch(
                """SELECT t.name FROM document_tags dt
                   JOIN tags t ON t.id = dt.tag_id
                   WHERE dt.doc_id = $1""",
                uuid.UUID(doc_id),
            )
            doc["tags"] = [tr["name"] for tr in tag_rows]

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

            # Carry forward flat columns from old doc
            old_brain_path = old_row.get("brain_path")
            old_brain_tier = old_row.get("brain_tier")
            old_source_file = old_row.get("source_file")
            old_scope = old_row.get("scope")
            old_summary = old_row.get("summary")

            # Carry forward metadata JSONB (merge old metadata)
            old_metadata = old_row.get("metadata")
            if isinstance(old_metadata, dict):
                metadata_val = old_metadata
            elif old_metadata is None:
                metadata_val = {}
            elif isinstance(old_metadata, str):
                metadata_val = json.loads(old_metadata)
            else:
                metadata_val = {}

            # Carry forward concepts JSONB
            old_concepts = old_row.get("concepts")
            concepts_val = _ensure_list(old_concepts)

            new_row = await conn.fetchrow(
                """INSERT INTO knowledge_documents
                   (title, content, content_hash, doc_type, source_type,
                    source_project, oracle_name, brain_path, brain_tier,
                    source_file, scope, concepts, summary, metadata)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                   RETURNING id""",
                title, new_content, content_hash,
                old_row["doc_type"], old_row["source_type"],
                old_row["source_project"], old_row["oracle_name"],
                old_brain_path, old_brain_tier,
                old_source_file, old_scope,
                concepts_val, old_summary,
                metadata_val,
            )

            await conn.execute(
                "UPDATE knowledge_documents SET superseded_by = $1, updated_at = NOW() WHERE id = $2",
                new_row["id"], uuid.UUID(old_id),
            )

            await conn.execute(
                """INSERT INTO supersede_log (old_id, new_id, reason) VALUES ($1, $2, $3)""",
                uuid.UUID(old_id), new_row["id"], reason,
            )

            # Carry forward tags from old doc to new doc
            old_tag_rows = await conn.fetch(
                """SELECT t.name FROM document_tags dt
                   JOIN tags t ON t.id = dt.tag_id
                   WHERE dt.doc_id = $1""",
                uuid.UUID(old_id),
            )
            old_tags = [tr["name"] for tr in old_tag_rows]
            if old_tags:
                await self._sync_tags(conn, new_row["id"], old_tags)

            # Carry forward concepts from old doc to new doc (junction tables)
            old_concept_rows = await conn.fetch(
                """SELECT c.name FROM document_concepts dc
                   JOIN concepts c ON c.id = dc.concept_id
                   WHERE dc.doc_id = $1""",
                uuid.UUID(old_id),
            )
            old_concepts_list = [cr["name"] for cr in old_concept_rows]
            if old_concepts_list:
                await self._sync_concepts(conn, new_row["id"], old_concepts_list)

        return {"id": str(new_row["id"]), "superseded": old_id, "status": "superseded"}

    # --- Search ---

    async def search_fts(
        self,
        query: str,
        scope: str | None = None,
        doc_type: str | None = None,
        oracle: str | None = None,
        source_project: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Full-text search using tsvector + ILIKE merged via reciprocal rank fusion.

        Both tsvector and ILIKE queries always run. Results are merged with RRF
        so Thai/mixed-language content is findable even when tsvector returns
        false-positive matches from English documents.
        """
        tokens = [t for t in query.replace("|", "").split() if len(t) > 1]
        ts_expr = " | ".join(tokens) if tokens else query

        # Build shared filter conditions (without the search predicate)
        base_conditions = ["superseded_by IS NULL"]
        base_params: list = []
        idx = 1

        if scope:
            base_conditions.append(f"scope = ${idx}")
            base_params.append(scope)
            idx += 1
        if doc_type:
            base_conditions.append(f"doc_type = ${idx}")
            base_params.append(doc_type)
            idx += 1
        if oracle:
            base_conditions.append(f"oracle_name = ${idx}")
            base_params.append(oracle)
            idx += 1
        if source_project:
            base_conditions.append(f"source_project = ${idx}")
            base_params.append(source_project)
            idx += 1

        tag_join = ""
        if tags:
            tag_placeholders = ", ".join(f"${i}" for i in range(idx, idx + len(tags)))
            tag_join = f""" JOIN document_tags dt ON dt.doc_id = knowledge_documents.id
                             JOIN tags t ON t.id = dt.tag_id AND t.name IN ({tag_placeholders})"""
            base_params.extend(tags)
            idx += len(tags)

        base_where = " AND ".join(base_conditions) if base_conditions else "1=1"
        cols = "DISTINCT knowledge_documents.id, title, scope, doc_type, oracle_name, source_project, LEFT(content, 500) as content, created_at"

        async with self.pool.acquire() as conn:
            # Phase 1: tsvector FTS
            fts_where = base_where + f" AND search_vector @@ to_tsquery('simple', ${idx})"
            fts_params = base_params + [ts_expr, limit]
            fts_sql = f"""SELECT {cols},
                                 ts_rank_cd(search_vector, to_tsquery('simple', ${idx})) AS rank
                          FROM knowledge_documents{tag_join}
                          WHERE {fts_where}
                          ORDER BY rank DESC
                          LIMIT ${idx + 1}"""
            fts_rows = await conn.fetch(fts_sql, *fts_params)

            # Phase 2: ILIKE — always run, independent of Phase 1 results
            ilike_idx = idx + 1
            ilike_where = base_where + f" AND (title ILIKE ${idx} OR content ILIKE ${idx})"
            ilike_params = base_params + [f"%{query}%", limit]
            ilike_sql = f"""SELECT {cols},
                                   0.3 AS rank
                            FROM knowledge_documents{tag_join}
                            WHERE {ilike_where}
                            ORDER BY created_at DESC
                            LIMIT ${ilike_idx}"""
            ilike_rows = await conn.fetch(ilike_sql, *ilike_params)

        # Merge with reciprocal rank fusion (k=60)
        K = 60
        rrf: dict[str, dict] = {}
        seen_titles: set[str] = set()

        for result_set, weight in [(fts_rows, 1.0), (ilike_rows, 0.7)]:
            for rank_idx, row in enumerate(result_set, start=1):
                doc_id = str(row["id"])
                title = row["title"]
                # Dedup by title within ILIKE results (FTS keeps priority)
                if weight < 1.0 and title in seen_titles:
                    continue
                seen_titles.add(title)

                rrf_score = weight / (K + rank_idx)
                if doc_id in rrf:
                    rrf[doc_id]["score"] += rrf_score
                else:
                    rrf[doc_id] = {
                        "id": doc_id,
                        "title": title,
                        "scope": row["scope"],
                        "doc_type": row["doc_type"],
                        "oracle_name": row["oracle_name"],
                        "source_project": row["source_project"],
                        "score": rrf_score,
                        "content": row["content"] or "",
                        "created_at": row["created_at"],
                    }

        merged = sorted(rrf.values(), key=lambda d: d["score"], reverse=True)
        results = merged[:limit]

        # Enrich with tags (separate connection — previous conn was released)
        if results:
            doc_ids = [uuid.UUID(d["id"]) for d in results]
            async with self.pool.acquire() as conn:
                tag_rows = await conn.fetch(
                    """SELECT dt.doc_id, t.name FROM document_tags dt
                       JOIN tags t ON t.id = dt.tag_id
                       WHERE dt.doc_id = ANY($1)""",
                    doc_ids,
                )
            tag_map: dict[str, list[str]] = {}
            for tr in tag_rows:
                tag_map.setdefault(str(tr["doc_id"]), []).append(tr["name"])
            for r in results:
                r["tags"] = tag_map.get(r["id"], [])

        return results

    # --- Vector Search (pgvector) ---

    async def set_embedding(self, doc_id: str, vector: list[float]) -> None:
        """Store pgvector embedding for a document."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE knowledge_documents SET embedding = $1 WHERE id = $2",
                vector, uuid.UUID(doc_id),
            )

    async def search_similar(
        self,
        vector: list[float],
        scope: str | None = None,
        doc_type: str | None = None,
        oracle: str | None = None,
        source_project: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        threshold: float | None = None,
    ) -> list[dict]:
        """Vector similarity search using pgvector cosine distance."""
        conditions = ["kd.superseded_by IS NULL", "kd.embedding IS NOT NULL"]
        params: list = [vector]
        idx = 2

        if scope:
            conditions.append(f"kd.scope = ${idx}")
            params.append(scope)
            idx += 1
        if doc_type:
            conditions.append(f"kd.doc_type = ${idx}")
            params.append(doc_type)
            idx += 1
        if oracle:
            conditions.append(f"kd.oracle_name = ${idx}")
            params.append(oracle)
            idx += 1
        if source_project:
            conditions.append(f"kd.source_project = ${idx}")
            params.append(source_project)
            idx += 1

        threshold_cond = ""
        if threshold is not None:
            threshold_cond = f" AND 1 - (kd.embedding <=> $1) >= {threshold}"

        tag_filter = ""
        if tags:
            tag_placeholders = ", ".join(f"${i}" for i in range(idx, idx + len(tags)))
            tag_filter = f""" AND kd.id IN (
                SELECT dt.doc_id FROM document_tags dt
                JOIN tags t ON t.id = dt.tag_id
                WHERE t.name IN ({tag_placeholders})
            )"""
            params.extend(tags)
            idx += len(tags)

        where = " AND ".join(conditions)
        sql = f"""SELECT kd.id, kd.title, kd.scope, kd.doc_type,
                         kd.oracle_name, kd.source_project,
                         LEFT(kd.content, 500) AS content, kd.created_at,
                         1 - (kd.embedding <=> $1) AS score
                  FROM knowledge_documents kd
                  WHERE {where}{tag_filter}{threshold_cond}
                  ORDER BY kd.embedding <=> $1
                  LIMIT ${idx}"""

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params, limit)

        results = [
            {
                "id": str(r["id"]), "title": r["title"], "scope": r["scope"],
                "doc_type": r["doc_type"], "oracle_name": r["oracle_name"],
                "source_project": r["source_project"],
                "content": r["content"] or "",
                "created_at": str(r["created_at"]),
                "score": r["score"],
            }
            for r in rows
        ]

        # Enrich with tags from junction table
        if results:
            doc_ids = [uuid.UUID(d["id"]) for d in results]
            async with self.pool.acquire() as conn:
                tag_rows = await conn.fetch(
                    """SELECT dt.doc_id, t.name FROM document_tags dt
                       JOIN tags t ON t.id = dt.tag_id
                       WHERE dt.doc_id = ANY($1)""",
                    doc_ids,
                )
            tag_map: dict[str, list[str]] = {}
            for tr in tag_rows:
                tag_map.setdefault(str(tr["doc_id"]), []).append(tr["name"])
            for r in results:
                r["tags"] = tag_map.get(r["id"], [])

        return results

    async def clear_embedding(self, doc_id: str) -> None:
        """NULL out the pgvector embedding to exclude doc from ANN results."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE knowledge_documents SET embedding = NULL WHERE id = $1",
                uuid.UUID(doc_id),
            )

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

    async def list_tags(self, search: str | None = None, limit: int = 50) -> list[dict]:
        async with self.pool.acquire() as conn:
            if search:
                rows = await conn.fetch(
                    """SELECT t.name, COUNT(dt.doc_id) AS doc_count
                       FROM tags t
                       LEFT JOIN document_tags dt ON dt.tag_id = t.id
                       LEFT JOIN knowledge_documents kd ON kd.id = dt.doc_id AND kd.superseded_by IS NULL
                       WHERE t.name ILIKE $1
                       GROUP BY t.name
                       ORDER BY doc_count DESC LIMIT $2""",
                    f"%{search}%", limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT t.name, COUNT(dt.doc_id) AS doc_count
                       FROM tags t
                       LEFT JOIN document_tags dt ON dt.tag_id = t.id
                       LEFT JOIN knowledge_documents kd ON kd.id = dt.doc_id AND kd.superseded_by IS NULL
                       GROUP BY t.name
                       ORDER BY doc_count DESC LIMIT $1""",
                    limit,
                )
        return [{"name": r["name"], "doc_count": r["doc_count"]} for r in rows]

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
        tags: list[str] | None = None,
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

        tag_join = ""
        if tags:
            tag_placeholders = ", ".join(f"${i}" for i in range(idx, idx + len(tags)))
            tag_join = f""" JOIN document_tags dt ON dt.doc_id = knowledge_documents.id
                             JOIN tags t ON t.id = dt.tag_id AND t.name IN ({tag_placeholders})"""
            params.extend(tags)
            idx += len(tags)

        params.append(limit)
        params.append(offset)
        where = " AND ".join(conditions) if conditions else "1=1"
        direction = "DESC" if order == "newest" else "ASC"

        sql = f"""SELECT DISTINCT knowledge_documents.id, title, scope, doc_type, oracle_name, source_project, created_at,
                         LEFT(content, 500) as content, summary
                  FROM knowledge_documents{tag_join}
                  WHERE {where}
                  ORDER BY created_at {direction}
                  LIMIT ${idx} OFFSET ${idx+1}"""

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        results = [
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

        # Enrich with tags from junction table
        if results:
            doc_ids = [uuid.UUID(d["id"]) for d in results]
            async with self.pool.acquire() as conn:
                tag_rows = await conn.fetch(
                    """SELECT dt.doc_id, t.name FROM document_tags dt
                       JOIN tags t ON t.id = dt.tag_id
                       WHERE dt.doc_id = ANY($1)""",
                    doc_ids,
                )
            tag_map: dict[str, list[str]] = {}
            for tr in tag_rows:
                tag_map.setdefault(str(tr["doc_id"]), []).append(tr["name"])
            for r in results:
                r["tags"] = tag_map.get(r["id"], [])

        return results


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

    async def find_by_source_file(
        self, source_file: str, source_project: str, include_hash: bool = False,
    ) -> dict | None:
        cols = "id, source_file" + (", content_hash, title" if include_hash else "")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""SELECT {cols} FROM knowledge_documents
                   WHERE source_file = $1 AND source_project = $2 AND superseded_by IS NULL
                   LIMIT 1""",
                source_file, source_project,
            )
        if row:
            result = {"id": str(row["id"]), "source_file": row["source_file"]}
            if include_hash:
                result["content_hash"] = row["content_hash"]
                result["title"] = row["title"]
            return result
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


    # --- Tag Sync Helper ---

    async def _sync_tags(
        self, conn: asyncpg.Connection, doc_id: uuid.UUID, tags: list[str],
    ) -> None:
        """Insert tags into junction tables (tags + document_tags)."""
        for tag_name in tags:
            await conn.execute(
                "INSERT INTO tags (name) VALUES ($1) ON CONFLICT (name) DO NOTHING",
                tag_name,
            )
            tag_row = await conn.fetchrow(
                "SELECT id FROM tags WHERE name = $1", tag_name,
            )
            await conn.execute(
                """INSERT INTO document_tags (doc_id, tag_id)
                   VALUES ($1, $2) ON CONFLICT DO NOTHING""",
                doc_id, tag_row["id"],
            )

    async def _sync_concepts(
        self, conn: asyncpg.Connection, doc_id: uuid.UUID, concepts: list[str],
    ) -> None:
        """Insert concepts into junction tables (concepts + document_concepts)."""
        for concept in concepts:
            await conn.execute(
                "INSERT INTO concepts (name) VALUES ($1) ON CONFLICT (name) DO NOTHING",
                concept,
            )
            concept_row = await conn.fetchrow(
                "SELECT id FROM concepts WHERE name = $1", concept,
            )
            await conn.execute(
                """INSERT INTO document_concepts (doc_id, concept_id)
                   VALUES ($1, $2) ON CONFLICT DO NOTHING""",
                doc_id, concept_row["id"],
            )

    # --- Cleanup (for tests) ---

    async def clean_pending_reviews(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM pending_reviews")

    # --- Tag Rules (v4 assistant) ---

    async def upsert_tag_rule(
        self,
        tag_name: str,
        handler: str,
        description: str | None = None,
        auto_classify: bool = True,
        alert_on_due: bool = False,
        collect_related: bool = False,
        schedule: str | None = None,
        config: dict | None = None,
        enabled: bool = True,
    ) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO tag_rules (tag_name, handler, description, auto_classify,
                   alert_on_due, collect_related, schedule, config, enabled)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                   ON CONFLICT (tag_name) DO UPDATE SET
                   handler = $2, description = $3, auto_classify = $4,
                   alert_on_due = $5, collect_related = $6, schedule = $7,
                   config = $8, enabled = $9
                   RETURNING id, tag_name, handler, enabled, created_at""",
                tag_name, handler, description, auto_classify,
                alert_on_due, collect_related, schedule,
                config or {}, enabled,
            )
        return _row_to_dict(row)

    async def get_tag_rule(self, tag_name: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM tag_rules WHERE tag_name = $1", tag_name,
            )
        return _row_to_dict(row) if row else None

    async def list_tag_rules(self, enabled_only: bool = False) -> list[dict]:
        async with self.pool.acquire() as conn:
            if enabled_only:
                rows = await conn.fetch(
                    "SELECT * FROM tag_rules WHERE enabled = true ORDER BY tag_name"
                )
            else:
                rows = await conn.fetch("SELECT * FROM tag_rules ORDER BY tag_name")
        return [_row_to_dict(r) for r in rows]

    async def delete_tag_rule(self, tag_name: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM tag_rules WHERE tag_name = $1", tag_name,
            )
        parts = result.split()
        return int(parts[1]) > 0 if len(parts) > 1 and parts[1].isdigit() else False

    # --- Scheduled Tasks (v4 assistant) ---

    async def create_scheduled_task(
        self,
        doc_id: str | None,
        tag_name: str,
        task_type: str = "reminder",
        due_date: str | None = None,
        recurrence: str | None = None,
        alert_before: str = "1 hour",
        metadata: dict | None = None,
    ) -> dict:
        from datetime import datetime

        # Convert due_date string to datetime
        _due_date = datetime.fromisoformat(due_date) if due_date else None

        # Convert alert_before string to SQL interval literal
        _alert_interval = _parse_interval(alert_before)

        async with self.pool.acquire() as conn:
            # Check for existing pending task for same doc+tag
            if doc_id:
                existing = await conn.fetchrow(
                    """SELECT id FROM scheduled_tasks
                       WHERE doc_id = $1 AND tag_name = $2 AND status = 'pending'""",
                    uuid.UUID(doc_id), tag_name,
                )
                if existing:
                    return {"status": "exists", "id": str(existing["id"])}

            row = await conn.fetchrow(
                f"""INSERT INTO scheduled_tasks
                   (doc_id, tag_name, task_type, due_date, recurrence, alert_before, metadata)
                   VALUES ($1, $2, $3, $4, $5, INTERVAL '{_alert_interval}', $6)
                   RETURNING id, created_at""",
                uuid.UUID(doc_id) if doc_id else None,
                tag_name,
                task_type,
                _due_date,
                recurrence,
                metadata or {},
            )
        return {"status": "created", "id": str(row["id"]), "created_at": str(row["created_at"])}

    async def get_due_tasks(self, now: str | None = None) -> list[dict]:
        """Get pending tasks where due_date - alert_before <= now and not yet alerted in this window."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT st.*, kd.title, kd.content
                   FROM scheduled_tasks st
                   LEFT JOIN knowledge_documents kd ON kd.id = st.doc_id
                   WHERE st.status = 'pending'
                     AND st.due_date IS NOT NULL
                     AND (st.due_date - st.alert_before) <= COALESCE($1::timestamptz, NOW())
                     AND (st.last_alerted IS NULL
                          OR st.last_alerted < (COALESCE($1::timestamptz, NOW()) - st.alert_before))
                   ORDER BY st.due_date""",
                now,
            )
        return [_row_to_dict(r) for r in rows]

    async def mark_task_alerted(self, task_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE scheduled_tasks
                   SET last_alerted = NOW(),
                       notified_at = array_append(notified_at, NOW())
                   WHERE id = $1""",
                uuid.UUID(task_id),
            )

    async def resolve_task(self, task_id: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE scheduled_tasks SET status = 'completed'
                   WHERE id = $1 AND status = 'pending'""",
                uuid.UUID(task_id),
            )
        parts = result.split()
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0 > 0

    async def list_scheduled_tasks(
        self, status: str | None = "pending", tag_name: str | None = None,
    ) -> list[dict]:
        async with self.pool.acquire() as conn:
            conditions = []
            params = []
            idx = 1
            if status:
                conditions.append(f"st.status = ${idx}")
                params.append(status)
                idx += 1
            if tag_name:
                conditions.append(f"st.tag_name = ${idx}")
                params.append(tag_name)
                idx += 1
            where = " AND ".join(conditions) if conditions else "TRUE"
            rows = await conn.fetch(
                f"""SELECT st.*, kd.title
                    FROM scheduled_tasks st
                    LEFT JOIN knowledge_documents kd ON kd.id = st.doc_id
                    WHERE {where}
                    ORDER BY st.due_date NULLS LAST, st.created_at DESC""",
                *params,
            )
        return [_row_to_dict(r) for r in rows]

    # --- Alert Log (v4 assistant) ---

    async def create_alert(
        self,
        task_id: str | None,
        doc_id: str | None,
        tag_name: str,
        channel: str,
        message: str,
    ) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO alert_log (task_id, doc_id, tag_name, channel, message)
                   VALUES ($1, $2, $3, $4, $5)
                   RETURNING id, sent_at""",
                uuid.UUID(task_id) if task_id else None,
                uuid.UUID(doc_id) if doc_id else None,
                tag_name, channel, message,
            )
        return {"id": str(row["id"]), "sent_at": str(row["sent_at"])}

    async def get_recent_alerts(self, limit: int = 50) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM alert_log ORDER BY sent_at DESC LIMIT $1""", limit,
            )
        return [_row_to_dict(r) for r in rows]

    # --- Document Chunks (v4) ---

    async def add_chunk(self, doc_id: str, chunk_index: int, content: str) -> str:
        """Insert a document chunk. Returns chunk UUID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO document_chunks (doc_id, chunk_index, content)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (doc_id, chunk_index) DO UPDATE SET content = $3
                   RETURNING id""",
                uuid.UUID(doc_id), chunk_index, content,
            )
        return str(row["id"])

    async def set_chunk_embedding(self, chunk_id: str, vector: list[float]) -> None:
        """Store pgvector embedding for a chunk."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE document_chunks SET embedding = $1 WHERE id = $2",
                vector, uuid.UUID(chunk_id),
            )

    async def search_chunks(
        self, vector: list[float], limit: int = 5, threshold: float | None = None,
    ) -> list[dict]:
        """Search document chunks by vector similarity. Returns chunks with parent doc info."""
        threshold_cond = ""
        if threshold is not None:
            threshold_cond = f" AND 1 - (dc.embedding <=> $1) >= {threshold}"
        sql = f"""SELECT dc.id AS chunk_id, dc.doc_id, dc.chunk_index, dc.content,
                         kd.title, kd.scope, kd.doc_type,
                         1 - (dc.embedding <=> $1) AS score
                  FROM document_chunks dc
                  JOIN knowledge_documents kd ON kd.id = dc.doc_id
                  WHERE dc.embedding IS NOT NULL AND kd.superseded_by IS NULL{threshold_cond}
                  ORDER BY dc.embedding <=> $1
                  LIMIT $2"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, vector, limit)
        return [
            {
                "chunk_id": str(r["chunk_id"]),
                "doc_id": str(r["doc_id"]),
                "chunk_index": r["chunk_index"],
                "content": r["content"],
                "title": r["title"],
                "scope": r["scope"],
                "doc_type": r["doc_type"],
                "score": r["score"],
            }
            for r in rows
        ]

    async def get_chunks(self, doc_id: str) -> list[dict]:
        """Get all chunks for a document, ordered by chunk_index."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, doc_id, chunk_index, content
                   FROM document_chunks WHERE doc_id = $1
                   ORDER BY chunk_index""",
                uuid.UUID(doc_id),
            )
        return [
            {
                "id": str(r["id"]), "doc_id": str(r["doc_id"]),
                "chunk_index": r["chunk_index"], "content": r["content"],
            }
            for r in rows
        ]

    async def delete_chunks(self, doc_id: str) -> int:
        """Delete all chunks for a document. Returns number deleted."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM document_chunks WHERE doc_id = $1",
                uuid.UUID(doc_id),
            )
        parts = result.split()
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0


    async def fix_doc_types(
        self,
        from_type: str,
        to_type: str,
        source_type: str | None = None,
        dry_run: bool = True,
    ) -> dict:
        """Batch update doc_type for documents matching criteria.

        Used to fix incorrectly classified documents (e.g., LINE messages
        auto-classified as 'task' that should be 'note').

        Args:
            from_type: Current doc_type to match (e.g., 'task')
            to_type: New doc_type to set (e.g., 'note')
            source_type: Only match docs with this source_type (e.g., 'line-user')
            dry_run: If True, only report what would be changed

        Returns:
            dict with matched count, updated count, and sample docs
        """
        # Validate doc_types
        from src.ingest.oracle_paths import validate_doc_type
        validate_doc_type(to_type)
        # from_type might be a legacy alias like 'task' → allow it
        if from_type not in ("task",) and from_type not in validate_doc_type.__globals__.get("VALID_DOC_TYPES", set()):
            # Allow legacy 'task' as from_type
            pass

        # Count matching docs
        if source_type:
            count = await self.pool.fetchval(
                """SELECT COUNT(*) FROM knowledge_documents
                   WHERE doc_type = $1 AND source_type = $2 AND superseded_by IS NULL""",
                from_type, source_type,
            )
        else:
            count = await self.pool.fetchval(
                """SELECT COUNT(*) FROM knowledge_documents
                   WHERE doc_type = $1 AND superseded_by IS NULL""",
                from_type,
            )

        if count == 0:
            return {"matched": 0, "updated": 0, "dry_run": dry_run, "sample": []}

        # Get sample docs
        async with self.pool.acquire() as conn:
            if source_type:
                rows = await conn.fetch(
                    """SELECT id, title, doc_type, source_type, left(content, 80) as preview
                       FROM knowledge_documents
                       WHERE doc_type = $1 AND source_type = $2 AND superseded_by IS NULL
                       ORDER BY created_at DESC LIMIT 5""",
                    from_type, source_type,
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, title, doc_type, source_type, left(content, 80) as preview
                       FROM knowledge_documents
                       WHERE doc_type = $1 AND superseded_by IS NULL
                       ORDER BY created_at DESC LIMIT 5""",
                    from_type,
                )

        sample_docs = [
            {"id": str(r["id"]), "title": r["title"], "doc_type": r["doc_type"],
             "source_type": r["source_type"], "preview": r["preview"]}
            for r in rows
        ]

        if dry_run:
            return {
                "matched": count,
                "updated": 0,
                "dry_run": True,
                "from_type": from_type,
                "to_type": to_type,
                "source_type": source_type,
                "sample": sample_docs,
            }

        # Perform the update
        if source_type:
            result = await self.pool.execute(
                """UPDATE knowledge_documents SET doc_type = $1, updated_at = NOW()
                   WHERE doc_type = $2 AND source_type = $3 AND superseded_by IS NULL""",
                to_type, from_type, source_type,
            )
        else:
            result = await self.pool.execute(
                """UPDATE knowledge_documents SET doc_type = $1, updated_at = NOW()
                   WHERE doc_type = $2 AND superseded_by IS NULL""",
                to_type, from_type,
            )

        updated = int(result.split()[-1]) if result else 0

        # Also update any scheduled_tasks linked to these docs
        if source_type:
            task_updates = await self.pool.execute(
                """DELETE FROM scheduled_tasks
                   WHERE doc_id IN (
                       SELECT id FROM knowledge_documents
                       WHERE doc_type = $1 AND source_type = $2 AND superseded_by IS NULL
                   )""",
                to_type, source_type,
            )
        else:
            task_updates = await self.pool.execute(
                """DELETE FROM scheduled_tasks
                   WHERE doc_id IN (
                       SELECT id FROM knowledge_documents
                       WHERE doc_type = $1 AND superseded_by IS NULL
                   )""",
                to_type,
            )

        tasks_removed = int(task_updates.split()[-1]) if task_updates else 0

        return {
            "matched": count,
            "updated": updated,
            "tasks_removed": tasks_removed,
            "dry_run": False,
            "from_type": from_type,
            "to_type": to_type,
            "source_type": source_type,
            "sample": sample_docs,
        }


async def _init_codecs(conn: asyncpg.Connection) -> None:
    """Register jsonb + pgvector codecs."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await register_vector(conn)


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


def _parse_interval(interval_str: str) -> str:
    """Parse a human-readable interval string into a PostgreSQL interval literal.

    Examples: '1 hour' → '1 hours', '30 minutes' → '30 minutes', '2 days' → '2 days'
    """
    # Simple pass-through for common formats that PostgreSQL understands
    valid_units = {"second", "seconds", "minute", "minutes", "hour", "hours", "day", "days", "week", "weeks"}
    parts = interval_str.strip().lower().split(None, 1)
    if len(parts) == 2 and parts[1] in valid_units:
        return interval_str.strip()
    # Fallback: default to 1 hour
    return "1 hour"


def _row_to_dict(row: asyncpg.Record) -> dict:
    d = {}
    for key in row.keys():
        val = row[key]
        if isinstance(val, uuid.UUID):
            val = str(val)
        d[key] = val
    return d