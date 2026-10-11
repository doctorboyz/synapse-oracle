"""Defrag — compact duplicate documents using content_hash + cross-scope pgvector ANN."""

import logging

from src.db.pg_store import PgStore
from src.embed.ollama import OllamaEmbedder

log = logging.getLogger("synapse.defrag")


async def defrag(
    pg: PgStore,
    embedder: OllamaEmbedder | None = None,
    scope: str | None = None,
    tags: list[str] | None = None,
    cross_scope: bool = False,
    similarity_threshold: float = 0.95,
    dry_run: bool = False,
) -> dict:
    """Find and compact duplicate documents.

    Two modes:
    - Exact duplicates: same content_hash (always checked — no scope boundary)
    - Semantic duplicates: detected via pgvector ANN search (if embedder available)

    When cross_scope=True, ANN search spans all tags.
    """
    all_docs = await pg.list_docs(scope=scope, tags=tags, limit=10000, order="newest")

    if not all_docs:
        return {
            "duplicates_found": 0,
            "merged_duplicates": 0,
            "removed_duplicates": 0,
            "compacted": 0,
            "errors": 0,
            "groups": [],
        }

    # Phase 1: Exact duplicates by content_hash only (no scope boundary)
    # One bulk query — never fetch docs one-by-one (no N+1)
    all_hashes = await pg.list_doc_hashes(scope=scope, tags=tags)
    seen_hashes: dict[str, list[dict]] = {}
    for doc in all_hashes:
        if not doc.get("content_hash"):
            continue
        seen_hashes.setdefault(doc["content_hash"], []).append(doc)

    groups = []
    total_merged = 0
    total_removed = 0
    total_errors = 0

    for ch, docs in seen_hashes.items():
        if len(docs) <= 1:
            continue
        group_info = {
            "title": docs[0].get("title", ""),
            "tags": docs[0].get("tags", []),
            "count": len(docs),
            "keep": docs[0]["id"],
            "supersede": [d["id"] for d in docs[1:]],
            "type": "exact_duplicate",
        }
        if dry_run:
            group_info["action"] = "would_supersede"
            groups.append(group_info)
            total_merged += 1
            total_removed += len(docs) - 1
            continue

        for old_doc in docs[1:]:
            try:
                # Fetch content only for actual duplicates (rare), not for
                # every doc in the vault — this is not the phase-1 scan loop.
                full_doc = await pg.get(old_doc["id"], include_chain=False)
                await pg.supersede(
                    old_id=old_doc["id"],
                    new_content=(full_doc or {}).get("content", ""),
                    reason="defrag_exact_duplicate",
                )
                total_merged += 1
                total_removed += 1
                group_info["action"] = "superseded"
            except Exception as e:
                log.error("Failed to supersede %s: %s", old_doc["id"], e)
                total_errors += 1
                group_info["action"] = "error"

        groups.append(group_info)

    # Phase 2: Semantic duplicates via pgvector ANN
    if embedder and len(all_docs) > 1:
        sem_groups = await _semantic_defrag(
            pg, embedder, tags or ([scope] if scope else None), cross_scope, similarity_threshold, dry_run
        )
        groups.extend(sem_groups["groups"])
        total_merged += sem_groups["merged_duplicates"]
        total_removed += sem_groups["removed_duplicates"]
        total_errors += sem_groups["errors"]

    return {
        "duplicates_found": len(groups),
        "merged_duplicates": total_merged,
        "removed_duplicates": total_removed,
        "compacted": total_merged,
        "errors": total_errors,
        "groups": groups,
    }


async def _semantic_defrag(
    pg: PgStore,
    embedder: OllamaEmbedder,
    tags: list[str] | None,
    cross_scope: bool,
    threshold: float,
    dry_run: bool,
) -> dict:
    """Use pgvector ANN to find near-duplicate documents across tags."""
    groups = []
    merged = 0
    removed = 0
    errors = 0
    checked_ids = set()

    all_docs = await pg.list_docs(tags=tags, limit=10000, order="newest")
    doc_ids = {d["id"] for d in all_docs}

    for doc in all_docs:
        doc_id = doc["id"]
        if doc_id in checked_ids:
            continue

        full_doc = await pg.get(doc_id, include_chain=False)
        if not full_doc:
            continue

        try:
            vector = await embedder.embed(full_doc.get("content", "")[:4000])
        except Exception as e:
            log.warning("Embedding failed for %s: %s", doc_id, e)
            continue

        search_tags = None if cross_scope else tags
        results = await pg.search_similar(vector, tags=search_tags, limit=5)

        dup_group = []
        for r in results:
            rid = r.get("id")
            if rid == doc_id or rid not in doc_ids or rid in checked_ids:
                continue
            score = r.get("score", 0)
            if score >= threshold:
                dup_group.append({"id": rid, "score": score})

        if not dup_group:
            checked_ids.add(doc_id)
            continue

        group_info = {
            "title": full_doc.get("title", ""),
            "tags": full_doc.get("tags", []),
            "count": 1 + len(dup_group),
            "keep": doc_id,
            "supersede": [d["id"] for d in dup_group],
            "type": "semantic_duplicate",
            "similarity_scores": {d["id"]: d["score"] for d in dup_group},
        }

        if dry_run:
            group_info["action"] = "would_supersede"
            groups.append(group_info)
            merged += 1
            removed += len(dup_group)
            checked_ids.add(doc_id)
            for d in dup_group:
                checked_ids.add(d["id"])
            continue

        for d in dup_group:
            try:
                await pg.supersede(
                    old_id=d["id"],
                    new_content=full_doc.get("content", ""),
                    reason=f"defrag_semantic_duplicate (score={d['score']:.3f})",
                )
                merged += 1
                removed += 1
                group_info["action"] = "superseded"
            except Exception as e:
                log.error("Failed to semantic-supersede %s: %s", d["id"], e)
                errors += 1
                group_info["action"] = "error"

        groups.append(group_info)
        checked_ids.add(doc_id)
        for d in dup_group:
            checked_ids.add(d["id"])

    return {
        "groups": groups,
        "merged_duplicates": merged,
        "removed_duplicates": removed,
        "errors": errors,
    }
