#!/usr/bin/env python3
"""Fix LINE-sourced 'task' docs that were incorrectly auto-classified.

Changes doc_type='task' → 'note' for all LINE-sourced documents,
and removes auto-created scheduled_tasks linked to them.

Usage:
    # Dry-run (preview only):
    python3 scripts/fix_line_tasks.py

    # Apply the fix:
    python3 scripts/fix_line_tasks.py --apply
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Settings
from src.db.pg_store import PgStore


async def main():
    apply = "--apply" in sys.argv
    settings = Settings()
    pg = PgStore(settings)
    await pg.connect()

    try:
        result = await pg.fix_doc_types(
            from_type="task",
            to_type="note",
            source_type=None,  # All task docs
            dry_run=not apply,
        )

        if apply:
            print(f"✅ Updated {result['updated']} docs from 'task' → 'note'")
            print(f"   Removed {result.get('tasks_removed', 0)} scheduled tasks")
        else:
            print(f"🔍 Dry-run: {result['matched']} docs would change from 'task' → 'note'")
            if result.get('sample'):
                print("\nSample docs:")
                for doc in result['sample']:
                    print(f"  • [{doc['doc_type']}] {doc['title']}")
                    print(f"    source: {doc['source_type']} | preview: {doc['preview'][:60]}...")
            print("\nRun with --apply to make changes:")
            print("  python3 scripts/fix_line_tasks.py --apply")

    finally:
        await pg.close()


if __name__ == "__main__":
    asyncio.run(main())
