"""
vault_migrator.py — Import ψ/memory/ from all oracle repos into synapse vault.

Scans ψ/memory/learnings/*.md and ψ/memory/retrospectives/**/*.md from every
oracle repo under ~/Code/github.com/doctorboyz/, extracts metadata, and pushes
into synapse via Push.push_file().

Usage: python -m src.migrate.vault_migrator [--dry-run] [--repo emily-oracle]
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import Settings
from src.db.pg_store import PgStore
from src.embed.ollama import OllamaEmbedder
from src.ingest.push import Push
from src.ingest.oracle_paths import extract_metadata

log = logging.getLogger("synapse.migrate")

ORACLE_REPOS = Path.home() / "Code" / "github.com" / "doctorboyz"
KNOWN_ORACLES = [
    "emily-oracle", "nexus-oracle", "dev-oracle", "mkt-oracle",
    "god-port-oracle", "infra-oracle", "myfam",
]

MEMORY_SUBDIRS = ["learnings", "retrospectives", "knowledge"]


def scan_memory_files(repo_path: Path) -> list[dict]:
    """Scan repo for ψ/memory/ files with metadata."""
    memory_root = repo_path / "ψ" / "memory"
    if not memory_root.exists():
        return []

    files = []
    for subdir in MEMORY_SUBDIRS:
        sd = memory_root / subdir
        if not sd.exists():
            continue
        for md_file in sd.rglob("*.md"):
            if md_file.name == "MEMORY.md":
                continue
            rel = md_file.relative_to(repo_path)
            meta = extract_metadata(str(md_file), str(repo_path))
            files.append({
                "path": md_file,
                "rel_path": str(rel),
                "oracle": meta.get("oracle_name", repo_path.name.replace("-oracle", "")),
                "doc_type": meta.get("doc_type", "learning"),
                "brain_tier": meta.get("brain_tier", "extrinsic"),
                "scope": meta.get("scope", meta.get("oracle_name", "shared")),
            })
    return files


async def migrate(migrator: Push, repo_filter: str | None = None, dry_run: bool = False):
    """Scan and migrate ψ/memory from oracles."""
    repos = [r for r in KNOWN_ORACLES if not repo_filter or r == repo_filter]
    stats = {"scanned": 0, "imported": 0, "duplicate": 0, "error": 0, "files": []}

    for repo_name in repos:
        repo_path = ORACLE_REPOS / repo_name
        if not repo_path.exists():
            log.warning("Repo not found: %s", repo_path)
            continue

        files = scan_memory_files(repo_path)
        log.info("%s: %d files found", repo_name, len(files))

        for f in files:
            stats["scanned"] += 1
            if dry_run:
                print(f"  [DRY-RUN] {f['oracle']}/{f['doc_type']}: {f['rel_path']}")
                continue

            try:
                result = await migrator.push_file(
                    file_path=str(f["path"]),
                    scope=f["scope"],
                    doc_type=f["doc_type"],
                    embed=True,
                )
                status = result.get("status", "?")
                if status == "duplicate":
                    stats["duplicate"] += 1
                else:
                    stats["imported"] += 1
                    stats["files"].append({
                        "id": result.get("id", "?"),
                        "oracle": f["oracle"],
                        "rel_path": f["rel_path"],
                    })
                print(f"  [{status}] {f['oracle']}: {f['rel_path']}")
            except Exception as e:
                stats["error"] += 1
                log.error("Failed %s: %s", f["rel_path"], e)
                print(f"  [ERROR] {f['oracle']}: {f['rel_path']} — {e}")

    return stats


async def main():
    parser = argparse.ArgumentParser(description="Migrate ψ/memory to synapse vault")
    parser.add_argument("--dry-run", action="store_true", help="List files only")
    parser.add_argument("--repo", type=str, help="Migrate specific repo only")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    settings = Settings()
    pg = PgStore(settings)
    embedder = OllamaEmbedder(settings)

    await pg.connect()
    await pg.init_schema()

    before = await pg.stats()
    print(f"\nBefore: {before['total_documents']} docs in vault\n")

    push = Push(pg, embedder)
    stats = await migrate(push, repo_filter=args.repo, dry_run=args.dry_run)

    after = await pg.stats()
    print(f"\nAfter: {after['total_documents']} docs in vault")
    print(f"Scanned: {stats['scanned']}  Imported: {stats['imported']}  "
          f"Duplicate: {stats['duplicate']}  Error: {stats['error']}")

    await pg.close()

if __name__ == "__main__":
    asyncio.run(main())
