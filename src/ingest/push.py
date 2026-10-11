"""Knowledge push — single-store ingestion with pgvector."""

import logging
from pathlib import Path

from src.db.pg_store import PgStore
from src.embed.ollama import MAX_CHUNK_CHARS, OllamaEmbedder
from src.ingest.oracle_paths import extract_metadata, validate_doc_type
from src.ingest.obsidian_links import create_traces_from_links
from src.ingest.concepts import extract_concepts

log = logging.getLogger("synapse.ingest.push")

CHUNK_SIZE = 1500  # chars per chunk
CHUNK_OVERLAP = 200  # chars overlap between chunks


class Push:
    """Push knowledge into PostgreSQL with pgvector embeddings."""

    def __init__(self, pg: PgStore, embedder: OllamaEmbedder | None = None,
                 cache=None):
        self.pg = pg
        self.embedder = embedder
        self._cache = cache

    def _invalidate_cache(self) -> None:
        """Clear the search cache after a write so new knowledge is findable."""
        if self._cache is not None:
            try:
                self._cache.clear()
            except Exception as e:
                log.warning("Cache invalidation failed: %s", e)

    async def _summarize(self, content: str, model: str | None = None) -> str:
        """Summarize long content using OpenRouter (fallback to Ollama)."""
        from src.llm.openrouter_client import OpenRouterClient

        settings = self.embedder.settings if self.embedder else __import__("src.config").Settings()
        client = OpenRouterClient(settings)
        try:
            return await client.summarize(
                content,
                model=model or settings.openrouter_summary_model,
            )
        except Exception as e:
            log.warning("Summarization failed: %s", e)
            return content[:2000]

    async def _semantic_dedup(
        self,
        content: str,
        tags: list[str] | None = None,
        threshold: float = 0.85,
    ) -> dict | None:
        """Check for semantic duplicates via pgvector similarity.

        Returns {"status": "semantic_duplicate", "id", "tags"} if a near-duplicate
        exists, otherwise None.
        """
        if not self.embedder:
            return None
        try:
            vector = await self.embedder.embed(content[:MAX_CHUNK_CHARS])
            results = await self.pg.search_similar(vector, tags=tags, limit=1)
            if results and results[0].get("score", 0) >= threshold:
                match = results[0]
                log.info(
                    "Semantic duplicate detected (score=%.3f): '%s' tags=%s",
                    match["score"],
                    match.get("title", ""),
                    tags,
                )
                return {
                    "id": match.get("id", ""),
                    "tags": tags or [],
                    "status": "semantic_duplicate",
                    "similarity_score": match["score"],
                }
        except Exception as e:
            log.warning("Semantic dedup failed: %s", e)
        return None

    @staticmethod
    def chunk_text(content: str, chunk_size: int = CHUNK_SIZE,
                   overlap: int = CHUNK_OVERLAP) -> list[str]:
        """Split text into overlapping chunks for better retrieval granularity."""
        if len(content) <= chunk_size:
            return [content]
        chunks = []
        start = 0
        while start < len(content):
            end = min(start + chunk_size, len(content))
            chunks.append(content[start:end])
            start += chunk_size - overlap
        return chunks

    async def _chunk_and_embed(self, doc_id: str, content: str) -> int:
        """Chunk long content and store with embeddings. Returns chunk count."""
        if not self.embedder or len(content) <= CHUNK_SIZE:
            return 0
        chunks = self.chunk_text(content)
        chunk_ids: list[str] = []
        for i, chunk_str in enumerate(chunks):
            try:
                chunk_ids.append(await self.pg.add_chunk(doc_id, i, chunk_str))
            except Exception as e:
                log.warning("Chunk %d insert failed for %s: %s", i, doc_id, e)
        if not chunk_ids:
            return 0
        try:
            vectors = await self.embedder.embed_batch(
                [c[:MAX_CHUNK_CHARS] for c in chunks[:len(chunk_ids)]]
            )
            for chunk_id, vector in zip(chunk_ids, vectors):
                await self.pg.set_chunk_embedding(chunk_id, vector)
            count = len(chunk_ids)
        except Exception as e:
            log.warning("Chunk embedding failed for %s: %s", doc_id, e)
            return 0
        log.info("Chunked doc %s into %d chunks (size=%d, overlap=%d)",
                 doc_id, count, CHUNK_SIZE, CHUNK_OVERLAP)
        return count

    async def push_text(
        self,
        title: str,
        content: str,
        doc_type: str = "note",
        source_file: str | None = None,
        source_type: str = "manual",
        source_project: str | None = None,
        oracle_name: str | None = None,
        brain_path: str | None = None,
        brain_tier: str | None = None,
        concepts: list[str] | None = None,
        tags: list[str] | None = None,
        metadata: dict | None = None,
        embed: bool = True,
        trace_content: str | None = None,
        skip_semantic_dedup: bool = False,
    ) -> dict:
        validate_doc_type(doc_type)

        if concepts is None:
            concepts = extract_concepts(content)

        # Merge brain_path/brain_tier/source_file into metadata JSONB
        doc_metadata = dict(metadata) if metadata else {}
        if brain_path:
            doc_metadata.setdefault("brain_path", brain_path)
        if brain_tier:
            doc_metadata.setdefault("brain_tier", brain_tier)
        if source_file:
            doc_metadata.setdefault("source_file", source_file)

        # Semantic duplicate check (before storing)
        if not skip_semantic_dedup:
            dup_result = await self._semantic_dedup(content, tags)
            if dup_result:
                return dup_result

        result = await self.pg.add(
            title=title, content=content, doc_type=doc_type,
            source_type=source_type,
            source_project=source_project, oracle_name=oracle_name,
            concepts=concepts, tags=tags, metadata=doc_metadata,
        )

        if result["status"] != "duplicate":
            self._invalidate_cache()

        # Create traces from Obsidian-style [[links]] in content
        if result["status"] != "duplicate":
            try:
                trace_result = await create_traces_from_links(
                    self.pg, result["id"], trace_content or content, tags=tags
                )
                if trace_result["traces_created"] > 0:
                    log.info("Created %d traces from obsidian links in '%s'",
                             trace_result["traces_created"], title)
            except Exception as e:
                log.warning("Obsidian link trace creation failed: %s", e)

        if embed and self.embedder:
            try:
                vector = await self.embedder.embed(content[:MAX_CHUNK_CHARS])
                await self.pg.set_embedding(result["id"], vector)
            except Exception as e:
                log.warning("Vector embedding failed: %s", e)

        # Chunk long documents for granular retrieval
        if embed and len(content) > CHUNK_SIZE:
            try:
                await self._chunk_and_embed(result["id"], content)
            except Exception as e:
                log.warning("Chunking failed for %s: %s", result["id"], e)

        return result

    async def push_file(self, file_path: str, tags: list[str] | None = None,
                        doc_type: str | None = None, embed: bool = True) -> dict:
        path = Path(file_path)
        title = path.stem
        content = path.read_text(encoding="utf-8")

        meta = extract_metadata(str(path), str(path.parent))
        if tags is None:
            tags = meta.get("tags", [])
        if doc_type is None and "doc_type" in meta:
            doc_type = meta["doc_type"]

        return await self.push_text(
            title=title, content=content,
            doc_type=doc_type or "note",
            source_file=str(path), source_type="manual",
            source_project=meta.get("source_project"),
            oracle_name=meta.get("oracle_name"),
            metadata=meta.get("metadata"),
            tags=tags,
            embed=embed,
        )

    async def supersede_and_reindex(
        self,
        old_id: str,
        content: str,
        title: str | None = None,
        doc_type: str = "note",
        source_file: str | None = None,
        source_type: str = "scan_update",
        source_project: str | None = None,
        oracle_name: str | None = None,
        brain_path: str | None = None,
        brain_tier: str | None = None,
        concepts: list[str] | None = None,
        tags: list[str] | None = None,
        metadata: dict | None = None,
        reason: str = "content_updated",
    ) -> dict:
        """Supersede an existing document and re-embed in pgvector.

        Handles PG supersede + clear old embedding + embed new doc.
        Used when scanning detects an updated file (content_hash changed).
        `title` may be None to carry the old title forward.
        """
        if concepts is None:
            concepts = extract_concepts(content)

        # Merge legacy fields into metadata
        doc_metadata = dict(metadata) if metadata else {}
        if brain_path:
            doc_metadata.setdefault("brain_path", brain_path)
        if brain_tier:
            doc_metadata.setdefault("brain_tier", brain_tier)
        if source_file:
            doc_metadata.setdefault("source_file", source_file)

        result = await self.pg._supersede_raw(
            old_id=old_id,
            new_content=content,
            reason=reason,
            new_title=title,
        )
        new_id = result.get("id")
        if not new_id:
            return {"status": "error", "error": "supersede returned no id"}

        # Clear embedding from old (superseded) doc
        try:
            await self.pg.clear_embedding(old_id)
        except Exception as e:
            log.warning("clear_embedding failed for %s: %s", old_id, e)

        # Embed new doc
        if self.embedder:
            try:
                vector = await self.embedder.embed(content[:MAX_CHUNK_CHARS])
                await self.pg.set_embedding(new_id, vector)
            except Exception as e:
                log.warning("Vector embedding failed for %s: %s", new_id, e)

            # Chunk long documents
            if len(content) > CHUNK_SIZE:
                try:
                    await self._chunk_and_embed(new_id, content)
                except Exception as e:
                    log.warning("Chunking failed for %s: %s", new_id, e)

        self._invalidate_cache()
        return {"status": "superseded", "id": new_id, "old_id": old_id, "tags": tags}
