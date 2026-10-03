"""Benchmark — measure synapse retrieval quality

Metrics:
1. Token savings: context tokens with vs without synapse
2. R@5: recall at 5 (answer in top-5 results)
3. Time: query latency
"""

import time
import json
from pathlib import Path
from synapse.store.sqlite_store import SQLiteStore
from synapse.retrieve.hybrid_search import HybridSearch


# Ground truth: question → expected doc title substring
BENCHMARK_QUERIES = [
    {"query": "docker container naming patterns", "expected": "docker-infrastructure-patterns"},
    {"query": "svix webhook setup", "expected": "infrastructure-rebuild"},
    {"query": "oracle principles nothing deleted", "expected": "oracle-awakening"},
    {"query": "knowledge framework hybrid search", "expected": "knowledge-framework"},
    {"query": "retrospective session format", "expected": "infrastructure-rebuild"},
    {"query": "pgvector embedding search", "expected": "docker-infrastructure"},
    {"query": "openkb knowledge base", "expected": "knowledge-framework"},
    {"query": "minio s3 storage", "expected": "docker-infrastructure"},
    {"query": "redis cache queue", "expected": "infrastructure-rebuild"},
    {"query": "hook auto push learning", "expected": "knowledge-framework"},
]


def run_benchmark(vault_path: str) -> dict:
    """Run benchmark and return metrics."""
    vault = Path(vault_path)
    sqlite = SQLiteStore(vault)

    try:
        from synapse.store.lancedb_store import LanceDBStore
        lancedb = LanceDBStore(vault)
        search = HybridSearch(sqlite, lancedb)
    except ImportError:
        search = None

    hits_at_5 = 0
    hits_at_10 = 0
    total = len(BENCHMARK_QUERIES)
    latencies = []

    for bq in BENCHMARK_QUERIES:
        start = time.perf_counter()

        if search:
            results = search.search(bq["query"], limit=10)
        else:
            results = sqlite.search_fts5(bq["query"], limit=10)
            for r in results:
                r["score"] = abs(r["score"])

        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)

        titles = [r["title"].lower() for r in results]
        expected = bq["expected"].lower()

        if any(expected in t for t in titles[:5]):
            hits_at_5 += 1
        if any(expected in t for t in titles[:10]):
            hits_at_10 += 1

    stats = sqlite.stats()

    return {
        "total_queries": total,
        "r_at_5": round(hits_at_5 / total, 3) if total else 0,
        "r_at_10": round(hits_at_10 / total, 3) if total else 0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "total_documents": stats["total_documents"],
        "vault_path": str(vault_path),
    }


if __name__ == "__main__":
    import sys
    vault = sys.argv[1] if len(sys.argv) > 1 else ".synapse"
    result = run_benchmark(vault)
    print(json.dumps(result, indent=2))