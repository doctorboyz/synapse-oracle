"""One-shot dry-run of reconcile inside the synapse container.

Usage:
    docker cp scripts/detox_dryrun_once.py synapse:/app/scripts/detox_dryrun_once.py
    docker exec synapse python /app/scripts/detox_dryrun_once.py

Dry-run only: reports duplicates/conflicts/actions without writing.
Progress logs to stderr so long runs are visible.
"""
import asyncio
import logging
import sys

from src.config import Settings
from src.db.pg_store import PgStore
from src.embed.ollama import OllamaEmbedder
from src.reconcile import reconcile


async def main() -> None:
    # Progress visibility: INFO to stderr so the report file stays clean
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    settings = Settings()
    pg = PgStore(settings)
    await pg.connect()
    embedder = OllamaEmbedder(settings)

    print(f"[dryrun] start scope=None dry_run=True judge chain loading...", flush=True)
    result = await reconcile(
        pg=pg,
        embedder=embedder,
        settings=settings,
        scope=None,
        dry_run=True,
    )

    defrag = result.get("defrag", {})
    detox = result.get("detox", {})
    print("=== DRY-RUN REPORT ===", flush=True)
    print(f"defrag: duplicates_found={defrag.get('duplicates_found', 0)}, "
          f"merged={defrag.get('merged_duplicates', 0)}, "
          f"removed={defrag.get('removed_duplicates', 0)}", flush=True)
    print(f"detox: pairs_analyzed={detox.get('pairs_analyzed', 0)}, "
          f"conflicts_found={detox.get('conflicts_found', 0)}, "
          f"llm_errors={detox.get('llm_errors', 0)}, "
          f"errors={detox.get('errors', 0)}", flush=True)
    print(f"actions: {detox.get('actions', {})}", flush=True)
    for conflict in detox.get("conflicts", [])[:10]:
        analysis = conflict.get("analysis", {})
        print(f"- [{conflict.get('action')}] "
              f"{conflict.get('doc_a', {}).get('title', '?')!r} vs "
              f"{conflict.get('doc_b', {}).get('title', '?')!r}: "
              f"{analysis.get('reason', '')[:120]}", flush=True)

    await pg.close()


if __name__ == "__main__":
    asyncio.run(main())