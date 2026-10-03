"""Migrate scope values → tags + source_project (one-shot, idempotent).

Usage:
    python -m src.migrate.scope_to_tags [--dry-run]

Safe to run multiple times — skips already-migrated documents.
"""

import asyncio
import logging
from datetime import datetime, timezone

log = logging.getLogger("synapse.migrate.scope_to_tags")


async def migrate_scope_to_tags(pg, dry_run: bool = False) -> dict:
    """Copy scope → tags + source_project for all active documents.

    1. For each doc with a non-null scope:
       - Add scope value as a tag (if not already present)
       - Set source_project from scope (if source_project is null)
    2. Add source_project as a tag too (so "arra" is both a tag and source_project)
    """
    rows = await pg.pool.fetch(
        "SELECT id, scope, source_project, title FROM knowledge_documents "
        "WHERE superseded_by IS NULL AND scope IS NOT NULL AND scope != '' "
        "ORDER BY created_at"
    )

    if not rows:
        return {"total": 0, "tags_added": 0, "source_projects_set": 0, "skipped": 0}

    stats = {"total": len(rows), "tags_added": 0, "source_projects_set": 0, "skipped": 0}

    for row in rows:
        doc_id = row["id"]
        scope = row["scope"]
        source_project = row["source_project"]

        # Check if tag already exists for this doc
        existing_tags = await pg.pool.fetch(
            "SELECT t.name FROM document_tags dt "
            "JOIN tags t ON t.id = dt.tag_id "
            "WHERE dt.doc_id = $1",
            doc_id,
        )
        existing_tag_names = {r["name"] for r in existing_tags}

        tags_to_add = []
        if scope and scope not in existing_tag_names:
            tags_to_add.append(scope)
        if scope and scope not in existing_tag_names and not source_project:
            pass  # scope will be added above

        if not tags_to_add and (source_project or not scope):
            stats["skipped"] += 1
            continue

        if dry_run:
            stats["tags_added"] += len(tags_to_add)
            if not source_project and scope:
                stats["source_projects_set"] += 1
            continue

        # Add tags via upsert
        for tag_name in tags_to_add:
            tag_id = await pg.pool.fetchval(
                "INSERT INTO tags (name, created_at) VALUES ($1, $2) "
                "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
                "RETURNING id",
                tag_name,
                datetime.now(timezone.utc),
            )
            await pg.pool.execute(
                "INSERT INTO document_tags (doc_id, tag_id) VALUES ($1, $2) "
                "ON CONFLICT DO NOTHING",
                doc_id,
                tag_id,
            )
        stats["tags_added"] += len(tags_to_add)

        # Set source_project from scope if missing
        if not source_project and scope:
            if not dry_run:
                await pg.pool.execute(
                    "UPDATE knowledge_documents SET source_project = $1, updated_at = $2 "
                    "WHERE id = $3",
                    scope,
                    datetime.now(timezone.utc),
                    doc_id,
                )
            stats["source_projects_set"] += 1

    return stats


async def main():
    import sys
    from src.config import Settings
    from src.db.pg_store import PgStore

    dry_run = "--dry-run" in sys.argv
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    pg = PgStore(settings)

    try:
        await pg.start()
        stats = await migrate_scope_to_tags(pg, dry_run=dry_run)
        mode = "DRY RUN" if dry_run else "MIGRATION"
        log.info(
            "%s complete: total=%d tags_added=%d source_projects_set=%d skipped=%d",
            mode,
            stats["total"],
            stats["tags_added"],
            stats["source_projects_set"],
            stats["skipped"],
        )
    finally:
        await pg.stop()


if __name__ == "__main__":
    asyncio.run(main())
