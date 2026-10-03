"""Detox — detect and resolve conflicts using pgvector ANN pre-filter + LLM."""

import logging

from src.db.pg_store import PgStore
from src.embed.ollama import OllamaEmbedder
from src.reconcile.llm import analyze_conflict

log = logging.getLogger("synapse.detox")


async def detox(
    pg: PgStore,
    embedder: OllamaEmbedder | None = None,
    settings=None,
    scope: str | None = None,
    tags: list[str] | None = None,
    cross_scope: bool = False,
    similarity_threshold: float = 0.70,
    dry_run: bool = False,
) -> dict:
    """Detect conflicts between documents using ANN pre-filter + LLM analysis.

    Steps:
    1. Get all active docs (optionally filtered by tags)
    2. For each doc: embed -> pgvector ANN search (cross-tag if requested)
    3. Filter candidates by similarity threshold (default 0.70)
    4. Send high-similarity pairs to LLM for conflict analysis
    5. If conflict detected: merge + supersede

    Returns dict with: conflicts_found, conflicts_resolved, errors,
    pairs_analyzed, llm_errors, actions, conflicts, resolutions
    """
    all_docs = await pg.list_docs(scope=scope, tags=tags, limit=10000, order="newest")

    if not all_docs or len(all_docs) < 2:
        return {
            "conflicts_found": 0,
            "conflicts_resolved": 0,
            "errors": 0,
            "pairs_analyzed": 0,
            "llm_errors": 0,
            "actions": {},
            "conflicts": [],
            "resolutions": [],
        }

    doc_ids = {d["id"] for d in all_docs}
    checked_pairs = set()
    conflicts = []
    resolutions = []
    errors = 0
    llm_errors = 0
    pairs_analyzed = 0
    action_counts = {"merged": 0, "stale_cut": 0, "conflict_open": 0}

    if embedder:
        for doc in all_docs:
            doc_id = doc["id"]
            full_doc = await pg.get(doc_id, include_chain=False)
            if not full_doc:
                continue

            candidates = await _find_candidates(
                full_doc, embedder, pg, checked_pairs,
                tags=None if cross_scope else full_doc.get("tags"),
                threshold=similarity_threshold,
            )

            for candidate in candidates:
                pairs_analyzed += 1
                pair_key = tuple(sorted([doc_id, candidate["id"]]))
                checked_pairs.add(pair_key)

                if not settings:
                    continue

                result = await _analyze_and_resolve(
                    full_doc, candidate, settings, dry_run, pg
                )
                if result.get("llm_error"):
                    llm_errors += 1
                if result.get("conflict"):
                    conflicts.append(result["conflict"])
                    _count_action(action_counts, result["conflict"].get("action"))
                    if result.get("resolution"):
                        resolutions.append(result["resolution"])
                    if result.get("error"):
                        errors += 1
    else:
        # Fallback: pairwise comparison (same doc_type)
        for i, doc_a in enumerate(all_docs):
            for doc_b in all_docs[i + 1:]:
                if doc_a.get("doc_type") != doc_b.get("doc_type"):
                    continue

                pairs_analyzed += 1
                if not settings:
                    continue
                full_a = await pg.get(doc_a["id"], include_chain=False) or doc_a
                full_b = await pg.get(doc_b["id"], include_chain=False) or doc_b
                if not full_a or not full_b:
                    continue

                try:
                    result = await _analyze_and_resolve(
                        full_a, full_b, settings, dry_run, pg
                    )
                except Exception:
                    result: dict = {"llm_error": True}

                if result.get("llm_error"):
                    llm_errors += 1
                if result.get("conflict"):
                    conflicts.append(result["conflict"])
                    _count_action(action_counts, result["conflict"].get("action"))
                    if result.get("resolution"):
                        resolutions.append(result["resolution"])
                    if result.get("error"):
                        errors += 1

    return {
        "conflicts_found": len(conflicts),
        "conflicts_resolved": len(resolutions),
        "errors": errors,
        "pairs_analyzed": pairs_analyzed,
        "llm_errors": llm_errors,
        "actions": action_counts,
        "conflicts": conflicts,
        "resolutions": resolutions,
    }


def _count_action(action_counts: dict, action: str | None) -> None:
    """Tally reportable actions from conflict resolutions."""
    if action == "would_resolve":
        action_counts["stale_cut"] += 1
    elif action == "resolved":
        action_counts["merged"] += 1
    else:
        # conflict found but not resolved (dry_run without merged_content,
        # supersede failure, or resolution pending)
        action_counts["conflict_open"] += 1


async def _analyze_and_resolve(
    doc_a: dict, doc_b: dict, settings, dry_run: bool, pg: PgStore
) -> dict:
    """Analyze conflict between two docs and optionally resolve.

    Returns:
        {"conflict": info, "resolution": {...}} — conflict found and resolved
        {"conflict": info} — conflict found (dry_run or no merged_content)
        {"no_conflict": True} — analyzed, no conflict
        {"llm_error": True} — every judge model failed; caller counts llm_errors
        {"error": msg} — LLM or supersede failed
    """
    pair_key = tuple(sorted([doc_a["id"], doc_b["id"]]))
    try:
        analysis = await analyze_conflict(
            doc_a={"title": doc_a.get("title", ""), "content": (doc_a.get("content") or "")[:2000]},
            doc_b={"title": doc_b.get("title", ""), "content": (doc_b.get("content") or "")[:2000]},
            settings=settings,
        )
    except Exception as e:
        log.warning("LLM analysis failed for pair %s: %s", pair_key, e)
        return {"error": str(e)}

    if not analysis:
        return {"llm_error": True}

    if not analysis.get("is_conflict"):
        return {"no_conflict": True}

    conflict_info = {
        "doc_a": {"id": doc_a["id"], "title": doc_a.get("title", ""), "scope": doc_a.get("scope", "")},
        "doc_b": {"id": doc_b["id"], "title": doc_b.get("title", ""), "scope": doc_b.get("scope", "")},
        "analysis": analysis,
        "action": None,
    }

    if dry_run:
        conflict_info["action"] = "would_resolve"
        return {"conflict": conflict_info}

    if analysis.get("merged_content"):
        try:
            supersede_id = analysis.get("supersede_id", "a")
            old_doc = doc_a if supersede_id == "a" else doc_b
            merged = analysis["merged_content"]

            result = await pg.supersede(
                old_id=old_doc["id"],
                new_content=merged,
                reason=f"detox_conflict: {analysis.get('reason', 'conflict detected')}",
            )
            conflict_info["action"] = "resolved"
            conflict_info["new_id"] = result.get("id")
            return {
                "conflict": conflict_info,
                "resolution": {
                    "old_id": old_doc["id"],
                    "new_id": result.get("id"),
                    "reason": analysis.get("reason"),
                },
            }
        except Exception as e:
            log.error("Failed to resolve conflict: %s", e)
            conflict_info["action"] = "error"
            conflict_info["error"] = str(e)
            return {"conflict": conflict_info, "error": str(e)}

    return {"conflict": conflict_info}


async def _find_candidates(
    full_doc: dict,
    embedder: OllamaEmbedder,
    pg: PgStore,
    checked_pairs: set,
    tags: list[str] | None,
    threshold: float,
) -> list[dict]:
    """Find candidate docs via pgvector ANN that might conflict."""
    try:
        vector = await embedder.embed(full_doc.get("content", "")[:4000])
    except Exception as e:
        log.warning("Embedding failed: %s", e)
        return []

    results = await pg.search_similar(vector, tags=tags, limit=10)
    candidates = []

    for r in results:
        rid = r.get("id")
        if rid == full_doc["id"]:
            continue
        score = r.get("score", 0)
        if score < threshold:
            continue
        pair_key = tuple(sorted([full_doc["id"], rid]))
        if pair_key in checked_pairs:
            continue

        candidate_doc = await pg.get(rid, include_chain=False)
        if not candidate_doc:
            continue
        candidates.append(candidate_doc)

    return candidates
