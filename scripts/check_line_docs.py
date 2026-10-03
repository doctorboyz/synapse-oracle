#!/usr/bin/env python3
"""Check latest LINE-sourced docs in the database.

Usage:
    python3 scripts/check_line_docs.py [--limit N] [--fix]

Options:
    --limit N    Show N latest docs (default: 10)
    --fix        Also run fix-doctype (change task → note for LINE docs)
"""

import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Settings
from src.db.pg_store import PgStore


async def main():
    parser = argparse.ArgumentParser(description="Check latest LINE docs in database")
    parser.add_argument("--limit", type=int, default=10, help="Number of docs to show")
    parser.add_argument("--fix", action="store_true", help="Fix task→note for LINE docs")
    args = parser.parse_args()

    settings = Settings()
    pg = PgStore(settings)
    await pg.connect()

    try:
        # Latest LINE docs
        async with pg.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT kd.id, kd.title, kd.doc_type, kd.source_type, kd.source_project,
                       kd.oracle_name, kd.created_at,
                       left(kd.content, 150) as content_preview,
                       (SELECT jsonb_agg(t.name) FROM document_tags dt 
                        JOIN tags t ON t.id = dt.tag_id WHERE dt.doc_id = kd.id) as tags
                FROM knowledge_documents kd
                WHERE kd.source_type LIKE 'line%' OR kd.source_project = 'line-integration'
                ORDER BY kd.created_at DESC
                LIMIT $1
            """, args.limit)

            print(f"=== Latest {len(rows)} LINE docs ===\n")
            for r in rows:
                print(f"📌 {r['title']}")
                print(f"   doc_type: {r['doc_type']}")
                print(f"   source: {r['source_type']} / {r['source_project']}")
                print(f"   tags: {r['tags']}")
                print(f"   created: {r['created_at']}")
                print(f"   content: {r['content_preview']}...")
                print()

            # Count by doc_type
            type_counts = await conn.fetch("""
                SELECT doc_type, COUNT(*) as cnt
                FROM knowledge_documents 
                WHERE (source_type LIKE 'line%' OR source_project = 'line-integration')
                AND superseded_by IS NULL
                GROUP BY doc_type ORDER BY cnt DESC
            """)
            print("=== LINE docs by doc_type (active) ===")
            for r in type_counts:
                marker = " ⚠️ NEEDS FIX" if r['doc_type'] == 'task' else ""
                print(f"  {r['doc_type']}: {r['cnt']}{marker}")

            # Count task docs that need fixing
            task_count = await conn.fetchval("""
                SELECT COUNT(*) FROM knowledge_documents 
                WHERE doc_type = 'task' 
                AND (source_type LIKE 'line%' OR source_project = 'line-integration')
                AND superseded_by IS NULL
            """)
            print(f"\n⚠️  LINE task docs (should be 'note'): {task_count}")

            # Total
            total = await conn.fetchval("""
                SELECT COUNT(*) FROM knowledge_documents WHERE superseded_by IS NULL
            """)
            print(f"📊 Total active docs: {total}")

        if args.fix and task_count > 0:
            print(f"\n🔧 Fixing {task_count} LINE task docs → note...")
            result = await pg.fix_doc_types(
                from_type="task",
                to_type="note",
                source_type=None,  # Fix ALL task docs, not just LINE
                dry_run=False,
            )
            print(f"   Matched: {result.get('matched', 0)}")
            print(f"   Updated: {result.get('updated', 0)}")
            print(f"   Tasks removed: {result.get('tasks_removed', 0)}")
            print("✅ Done!")
        elif args.fix and task_count == 0:
            print("\n✅ No task docs to fix!")

    finally:
        await pg.close()


if __name__ == "__main__":
    asyncio.run(main())
