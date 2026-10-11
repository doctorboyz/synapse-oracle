"""Hybrid search — pgvector dense + PostgreSQL tsvector → Reciprocal Rank Fusion."""

import logging

from src.db.pg_store import PgStore
from src.embed.ollama import OllamaEmbedder, EmbeddingError

log = logging.getLogger("synapse.retrieve.hybrid")


def reciprocal_rank_fusion(
    result_lists: list[list[dict]],
    weights: list[float] | None = None,
    k: int = 60,
) -> list[dict]:
    if weights is None:
        weights = [1.0 / len(result_lists)] * len(result_lists)

    rrf_scores: dict[str, float] = {}
    doc_info: dict[str, dict] = {}

    for weight, results in zip(weights, result_lists):
        for rank, doc in enumerate(results, start=1):
            doc_id = doc["id"]
            score = weight / (k + rank)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + score

            if doc_id not in doc_info:
                # Core keys are canonical; extras (matched_chunk_content,
                # dense_source, content, ...) ride along first-write-wins
                core = {"id", "title", "tags", "doc_type", "oracle_name",
                        "source_project", "score"}
                doc_info[doc_id] = {
                    "id": doc_id,
                    "title": doc.get("title", ""),
                    "tags": list(doc.get("tags") or []),
                    "doc_type": doc.get("doc_type", ""),
                    "oracle_name": doc.get("oracle_name"),
                    "source_project": doc.get("source_project"),
                    **{key: val for key, val in doc.items() if key not in core},
                }
            else:
                # Merge tags from both sources
                existing_tags = set(doc_info[doc_id].get("tags") or [])
                new_tags = doc.get("tags") or []
                doc_info[doc_id]["tags"] = list(existing_tags | set(new_tags))

    return [
        {**doc_info[doc_id], "score": score}
        for doc_id, score in sorted(rrf_scores.items(), key=lambda x: -x[1])
    ]


def _merge_dense_results(
    doc_results: list[dict], chunk_hits: list[dict], limit: int,
) -> list[dict]:
    """Merge doc-level and chunk-level dense hits into one ranked list.

    - Best score per doc wins; a doc surfaced by its chunk keeps the
      matched chunk content for the caller.
    - Each doc id appears at most once (RRF downstream assumes that).
    """
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for d in doc_results:
        entry = dict(d)
        by_id[d["id"]] = entry
        order.append(d["id"])
    for ch in chunk_hits:
        doc_id = ch["doc_id"]
        entry = by_id.get(doc_id)
        if entry is None:
            by_id[doc_id] = {
                "id": doc_id,
                "title": ch.get("title", ""),
                "scope": ch.get("scope"),
                "doc_type": ch.get("doc_type"),
                "oracle_name": None,
                "source_project": None,
                "score": ch.get("score", 0.0),
                "dense_source": "chunk",
                "matched_chunk_content": ch.get("content", ""),
            }
            order.append(doc_id)
        elif ch.get("score", 0.0) > entry.get("score", 0.0) \
                and "matched_chunk_content" not in entry:
            # Best chunk for this doc (hits arrive score-sorted) — carry its
            # content. Later, lower-scored chunks must not overwrite it.
            entry["matched_chunk_content"] = ch.get("content", "")
            entry["dense_source"] = "chunk"
    merged = [by_id[doc_id] for doc_id in order]
    merged.sort(key=lambda d: -d.get("score", 0.0))
    return merged[:limit]


class HybridSearch:
    """pgvector dense + chunk-level + PostgreSQL tsvector → RRF fusion."""

    def __init__(self, pg: PgStore, embedder: OllamaEmbedder | None = None,
                 weights: list[float] | None = None, rrf_k: int = 60,
                 cache=None):
        self.pg = pg
        self.embedder = embedder
        self._weights = weights or [0.6, 0.4]
        self._rrf_k = rrf_k
        self._cache = cache

    async def _dense_with_chunks(
        self, vector: list[float], scope, doc_type, oracle, source_project,
        concepts, tags, limit: int,
    ) -> list[dict]:
        """Doc-level ANN + chunk-level ANN, merged by best score.

        Long docs (>MAX_CHUNK_CHARS) have their doc-level embedding truncated,
        so facts past the cutoff are only reachable via chunks. Without this
        merge, stored knowledge silently becomes unfindable on the dense path.
        """
        doc_results = await self.pg.search_similar(
            vector, scope=scope, doc_type=doc_type, oracle=oracle,
            source_project=source_project, tags=tags, concepts=concepts,
            limit=limit,
        )
        try:
            chunk_hits = await self.pg.search_chunks(vector, limit=limit)
        except Exception as e:
            log.warning("Chunk search failed, doc-level only: %s", e)
            chunk_hits = []
        return _merge_dense_results(doc_results, chunk_hits, limit)

    async def search(
        self,
        query: str,
        scope: str | None = None,
        doc_type: str | None = None,
        oracle: str | None = None,
        source_project: str | None = None,
        concepts: list[str] | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        mode: str = "hybrid",
    ) -> list[dict]:
        # Check cache first — key covers every filter that changes results
        if self._cache:
            cached = self._cache.get(
                query, tags=tags, mode=mode, limit=limit, doc_type=doc_type,
                oracle=oracle, source_project=source_project, concepts=concepts,
            )
            if cached is not None:
                return cached

        def _cache_put(results: list[dict]) -> list[dict]:
            if self._cache:
                self._cache.put(
                    query, results, tags=tags, mode=mode, limit=limit,
                    doc_type=doc_type, oracle=oracle,
                    source_project=source_project, concepts=concepts,
                )
            return results

        if mode == "dense":
            if not self.embedder:
                raise SearchError("Dense search requires OllamaEmbedder")
            vector = await self.embedder.embed(query)
            results = await self._dense_with_chunks(
                vector, scope, doc_type, oracle, source_project,
                concepts, tags, limit,
            )
            return _cache_put(results)

        if mode == "fts":
            results = await self.pg.search_fts(
                query, scope=scope, doc_type=doc_type, oracle=oracle,
                source_project=source_project, tags=tags, concepts=concepts,
                limit=limit,
            )
            return _cache_put(results)

        # Hybrid: dense (+chunks) + FTS via RRF
        if not self.embedder:
            results = await self.pg.search_fts(
                query, scope=scope, doc_type=doc_type, oracle=oracle,
                source_project=source_project, tags=tags, concepts=concepts,
                limit=limit,
            )
            return _cache_put(results)

        try:
            vector = await self.embedder.embed(query)
            # RRF with k=60 keeps a rank-20 candidate competitive
            # (~0.0075 vs rank-1's ~0.0098), so every source must offer a
            # wide pool before fusion. Truncating at limit*2 silently drops
            # docs the OTHER source ranks top — one fusion miss per corpus
            # (hybrid R@5 regression, 2026-10-11 kafka query).
            pool = max(limit * 4, 20)
            dense_results = await self._dense_with_chunks(
                vector, scope, doc_type, oracle, source_project,
                concepts, tags, pool,
            )
        except EmbeddingError as e:
            log.warning("Dense search failed, falling back to FTS: %s", e)
            results = await self.pg.search_fts(
                query, scope=scope, doc_type=doc_type, oracle=oracle,
                source_project=source_project, tags=tags, concepts=concepts,
                limit=limit,
            )
            return _cache_put(results)

        fts_results = await self.pg.search_fts(
            query, scope=scope, doc_type=doc_type, oracle=oracle,
            source_project=source_project, tags=tags, concepts=concepts,
            limit=pool,
        )

        if not dense_results and not fts_results:
            return []
        if not dense_results:
            return _cache_put(fts_results[:limit])
        if not fts_results:
            return _cache_put(dense_results[:limit])

        merged = reciprocal_rank_fusion(
            [dense_results, fts_results],
            weights=self._weights,
            k=self._rrf_k,
        )
        results = merged[:limit]

        return _cache_put(results)

    async def search_cross_scope(
        self,
        query: str,
        scopes: list[str],
        limit: int = 10,
        mode: str = "hybrid",
    ) -> list[dict]:
        """Search across multiple scopes, merging results via RRF for fairness."""
        per_scope: list[list[dict]] = []
        for scope in scopes:
            results = await self.search(
                query=query, scope=scope, limit=limit * 2, mode=mode,
            )
            per_scope.append(results)

        merged = reciprocal_rank_fusion(per_scope, weights=None, k=self._rrf_k)
        return merged[:limit]


class SearchError(Exception):
    pass
