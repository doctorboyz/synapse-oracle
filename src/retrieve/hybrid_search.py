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
                doc_info[doc_id] = {
                    "id": doc_id,
                    "title": doc.get("title", ""),
                    "tags": list(doc.get("tags") or []),
                    "doc_type": doc.get("doc_type", ""),
                    "oracle_name": doc.get("oracle_name"),
                    "source_project": doc.get("source_project"),
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


class HybridSearch:
    """pgvector dense + PostgreSQL tsvector → RRF fusion."""

    def __init__(self, pg: PgStore, embedder: OllamaEmbedder | None = None,
                 weights: list[float] | None = None, rrf_k: int = 60,
                 cache=None):
        self.pg = pg
        self.embedder = embedder
        self._weights = weights or [0.6, 0.4]
        self._rrf_k = rrf_k
        self._cache = cache

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
        # Check cache first
        if self._cache:
            cached = self._cache.get(query, tags=tags, mode=mode, limit=limit)
            if cached is not None:
                return cached

        if mode == "dense":
            if not self.embedder:
                raise SearchError("Dense search requires OllamaEmbedder")
            vector = await self.embedder.embed(query)
            return await self.pg.search_similar(
                vector, scope=scope, doc_type=doc_type, oracle=oracle,
                source_project=source_project, tags=tags, limit=limit,
            )

        if mode == "fts":
            return await self.pg.search_fts(
                query, scope=scope, doc_type=doc_type, oracle=oracle,
                source_project=source_project, tags=tags, limit=limit,
            )

        # Hybrid: dense + FTS via RRF
        if not self.embedder:
            return await self.pg.search_fts(
                query, scope=scope, doc_type=doc_type, oracle=oracle,
                source_project=source_project, tags=tags, limit=limit,
            )

        try:
            vector = await self.embedder.embed(query)
            dense_results = await self.pg.search_similar(
                vector, scope=scope, doc_type=doc_type, oracle=oracle,
                source_project=source_project, tags=tags, limit=limit * 2,
            )
        except EmbeddingError as e:
            log.warning("Dense search failed, falling back to FTS: %s", e)
            return await self.pg.search_fts(
                query, scope=scope, doc_type=doc_type, oracle=oracle,
                source_project=source_project, tags=tags, limit=limit,
            )

        fts_results = await self.pg.search_fts(
            query, scope=scope, doc_type=doc_type, oracle=oracle,
            source_project=source_project, tags=tags, limit=limit * 2,
        )

        if not dense_results and not fts_results:
            return []
        if not dense_results:
            return fts_results[:limit]
        if not fts_results:
            return dense_results[:limit]

        merged = reciprocal_rank_fusion(
            [dense_results, fts_results],
            weights=self._weights,
            k=self._rrf_k,
        )
        results = merged[:limit]

        if self._cache:
            self._cache.put(query, results, tags=tags, mode=mode, limit=limit)

        return results

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
