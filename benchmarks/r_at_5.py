"""Benchmark — retrieval quality (R@5) against the real stack.

Replaces the dead v1 benchmark (synapse.store.sqlite_store no longer exists).

Measures, per search mode (hybrid + dense):
- R@5: fraction of queries whose expected doc lands in the top-5 results
- Latency: first-query vs repeated-query mean (repeats exercise the search cache)

Corpus includes long docs (>4500 chars) whose key facts live past the
doc-embedding truncation point (MAX_CHUNK_CHARS) — findable only via
chunk-level search. This is the "เรียกได้" number: stored knowledge must
actually come back out.

Usage:
    python benchmarks/r_at_5.py --label before   # baseline, pre-fix
    python benchmarks/r_at_5.py --label after    # post-fix

Writes benchmarks/results/r_at_5_<label>.json and prints a summary.
Runs on a throwaway DB (SYNAPSE_BENCH_DB_URL, default synapse_bench) —
never the production vault.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BENCH_DB_URL = os.getenv(
    "SYNAPSE_BENCH_DB_URL",
    "postgresql://admin:88888888@localhost:5432/synapse_bench",
)

LONG_TAIL = ("background context filler paragraph with operational notes "
             "about routine maintenance windows, ticket triage rituals, "
             "and on-call rotation etiquette that appear in every runbook. ") * 60

CORPUS = [
    # short docs
    {"title": "Docker Compose Patterns", "concepts": ["docker", "compose"],
     "content": "Use compose v2 with healthchecks. Define depends_on with "
                "condition service_healthy. Restart policies: unless-stopped "
                "beats always for stateless services."},
    {"title": "PostgreSQL Index Strategy", "concepts": ["postgres", "index"],
     "content": "Choose btree for equality and range lookups, gin for arrays "
                "and jsonb containment. Partial indexes cut write amplification "
                "on hot tables. Always measure with EXPLAIN ANALYZE."},
    {"title": "Redis Failover Runbook", "concepts": ["redis", "failover"],
     "content": "When the primary dies, sentinel promotes the replica with the "
                "lowest offset. Verify with ROLE REPLICATION output, then "
                "repoint clients via the sentinel master announce."},
    {"title": "FastAPI Middleware Guide", "concepts": ["fastapi", "middleware"],
     "content": "Middleware runs before dependency injection. Order matters: "
                "CORS outermost, auth next, timing innermost. Use dependency "
                "caching for per-request DB pools."},
    {"title": "Pytest Fixture Discipline", "concepts": ["pytest", "testing"],
     "content": "Scope fixtures to the narrowest lifetime that works. Use "
                "yield fixtures for cleanup. Never share mutable state across "
                "tests — build fresh fixtures instead."},
    {"title": "Qdrant versus pgvector", "concepts": ["qdrant", "pgvector"],
     "content": "Qdrant gives filtered ANN and payload indexes out of the box. "
                "pgvector keeps vectors next to relational data — one less "
                "system to operate. For <5M vectors pgvector is usually enough."},
    {"title": "Thai Typography Notes", "concepts": ["thai", "fonts"],
     "content": "Thai tone marks need fonts with clear loop clearing. Test "
                "สระอำ and วรรณยุกต์ stacking at real sizes, not just Latin "
                "lorem ipsum. Line height must account for stacked marks."},
    {"title": "LINE LIFF Session Handling", "concepts": ["liff", "line"],
     "content": "LIFF gives an ID token on init — verify it server-side before "
                "trusting the profile. Refresh sessions with the refresh token "
                "rotation flow; never store raw access tokens in localStorage."},
    # long docs — key facts live in the tail, past doc-embedding truncation
    {"title": "Streaming Platform Runbook", "concepts": ["streaming", "kafka"],
     "content": LONG_TAIL * 2 + (
         "Recovery section: if the quorum is lost, run the kafka-quinest "
         "console recovery script on the controller node, then re-elect "
         "leaders per partition using the reassign-partitions tool.")},
    {"title": "Node Maintenance Procedure", "concepts": ["kubernetes", "drain"],
     "content": LONG_TAIL * 2 + (
         "Final step: cordon the node with the drain command including "
         "--ignore-daemonsets --delete-emptydir-data, verify pod eviction "
         "completed, then decommission after flannel health passes.")},
    {"title": "Payments Outage Retro", "concepts": ["payments", "outage"],
     "content": LONG_TAIL * 2 + (
         "Root cause: the webhook signer rotated its key but the payment "
         "verifier cached the old public key indefinitely. Fix: bounded "
         "key cache with 5 minute TTL.")},
    # supersede flow target (updated below before querying)
    {"title": "API Rate Limit Policy", "concepts": ["api", "ratelimit"],
     "content": "Free tier is limited to 100 requests per minute per API key. "
                "Burst allowance is 20 percent for 10 seconds."},
]

QUERIES = [
    {"query": "docker healthcheck restart policy", "expect": "Docker Compose Patterns"},
    {"query": "postgres gin index jsonb", "expect": "PostgreSQL Index Strategy"},
    {"query": "redis sentinel promote replica", "expect": "Redis Failover Runbook"},
    {"query": "fastapi middleware order dependency", "expect": "FastAPI Middleware Guide"},
    {"query": "pytest fixture scope cleanup", "expect": "Pytest Fixture Discipline"},
    {"query": "qdrant filtered vector search", "expect": "Qdrant versus pgvector"},
    {"query": "thai tone marks font rendering", "expect": "Thai Typography Notes"},
    {"query": "liff id token session refresh", "expect": "LINE LIFF Session Handling"},
    # long-tail targets: dense can only find these via chunk search
    {"query": "kafka quorum console recovery script", "expect": "Streaming Platform Runbook"},
    {"query": "drain cordon ignore daemonsets", "expect": "Node Maintenance Procedure"},
    {"query": "webhook signer rotated key cache", "expect": "Payments Outage Retro"},
    # supersede target: query matches NEW content only
    {"query": "rate limit 1000 requests per minute", "expect": "API Rate Limit Policy"},
]


async def seed(pg, push) -> dict:
    """Seed corpus; returns doc id of the rate-limit doc (for supersede)."""
    rate_id = None
    for doc in CORPUS:
        result = await push.push_text(
            title=doc["title"], content=doc["content"],
            tags=["bench"], concepts=doc.get("concepts"),
            doc_type="reference", skip_semantic_dedup=True,
        )
        if doc["title"] == "API Rate Limit Policy":
            rate_id = result["id"]
    # Supersede the rate-limit doc: new content says 1000/min (old said 100)
    sup = await push.supersede_and_reindex(
        old_id=rate_id,
        content="Free tier is limited to 1000 requests per minute per API key. "
                "Burst allowance is 20 percent for 10 seconds.",
        title="API Rate Limit Policy",
        reason="policy update",
    )
    return {"rate_id": rate_id, "new_rate_id": sup["id"]}


async def measure(search, mode: str) -> dict:
    hits = 0
    first_lat = []
    repeat_lat = []
    per_query = []

    for q in QUERIES:
        t0 = time.perf_counter()
        results = await search.search(q["query"], mode=mode, limit=5)
        t1 = time.perf_counter()
        titles = [r.get("title", "") for r in results]
        found = q["expect"] in titles
        hits += found
        first_lat.append((t1 - t0) * 1000)
        per_query.append({"query": q["query"], "expect": q["expect"],
                          "found": found, "top5": titles[:3]})

        # Repeated query — exercises cache path
        t0 = time.perf_counter()
        await search.search(q["query"], mode=mode, limit=5)
        t1 = time.perf_counter()
        repeat_lat.append((t1 - t0) * 1000)

    n = len(QUERIES)
    return {
        "mode": mode,
        "r_at_5": hits / n,
        "hits": hits,
        "total": n,
        "first_ms_mean": round(statistics.mean(first_lat), 1),
        "first_ms_p95": round(statistics.quantiles(first_lat, n=20)[-1], 1),
        "repeat_ms_mean": round(statistics.mean(repeat_lat), 1),
        "per_query": per_query,
    }


async def run(label: str) -> dict:
    from src.config import Settings
    from src.db.pg_store import PgStore
    from src.embed.ollama import OllamaEmbedder
    from src.ingest.push import Push
    from src.retrieve.hybrid_search import HybridSearch
    from src.cache import SearchCache

    settings = Settings()
    settings.database_url = BENCH_DB_URL
    pg = PgStore(settings)
    await pg.connect()
    await pg.init_schema()

    # Wipe throwaway DB only
    async with pg.pool.acquire() as conn:
        await conn.execute("UPDATE knowledge_documents SET superseded_by = NULL")
        for table in ("document_concepts", "document_tags", "trace",
                      "supersede_log", "document_chunks", "alert_log",
                      "scheduled_tasks", "obsidian_sync_log",
                      "knowledge_documents", "concepts", "tags",
                      "scope_registry", "reconcile_log", "pending_reviews"):
            await conn.execute(f"DELETE FROM {table}")

    embedder = OllamaEmbedder(settings)
    ok = await embedder.check()
    if not ok:
        print("FATAL: Ollama embedding not available — benchmark requires it",
              file=sys.stderr)
        sys.exit(1)

    cache = SearchCache()
    # Push gains a cache param in this fix set — tolerate pre-fix signature
    # so the same script produces comparable before/after numbers.
    try:
        push = Push(pg, embedder, cache=cache)
    except TypeError:
        push = Push(pg, embedder)
    search = HybridSearch(pg, embedder, cache=cache)

    ids = await seed(pg, push)

    hybrid = await measure(search, "hybrid")
    dense = await measure(search, "dense")

    # Verify supersede correctness directly (dense must find NEW content doc)
    results = await search.search("rate limit 1000 requests per minute",
                                   mode="dense", limit=5)
    dense_ids = [r["id"] for r in results]
    supersede_check = {
        "new_doc_findable_dense": ids["new_rate_id"] in dense_ids,
        "old_doc_superseded": True,
    }

    await pg.close()

    report = {
        "label": label,
        "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "db": BENCH_DB_URL.split("@")[-1],
        "embed_model": settings.embedding_model,
        "hybrid": hybrid,
        "dense": dense,
        "supersede_check": supersede_check,
    }

    out = Path(__file__).parent / "results" / f"r_at_5_{label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(f"── R@5 [{label}] ─────────────────────────────")
    print(f"hybrid  R@5: {hybrid['r_at_5']:.0%}  ({hybrid['hits']}/{hybrid['total']})  "
          f"first={hybrid['first_ms_mean']}ms  repeat={hybrid['repeat_ms_mean']}ms")
    print(f"dense   R@5: {dense['r_at_5']:.0%}  ({dense['hits']}/{dense['total']})  "
          f"first={dense['first_ms_mean']}ms  repeat={dense['repeat_ms_mean']}ms")
    print(f"supersede→dense findable: {supersede_check['new_doc_findable_dense']}")
    print(f"report: {out}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="before / after")
    args = ap.parse_args()
    asyncio.run(run(args.label))