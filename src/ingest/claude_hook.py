"""Claude Code hook — auto-ingest κ/ψ files into synapse via PostToolUse hook.

Replaces the deleted hook_handler.py (which depended on QdrantStore).
This module reads written files directly and pushes them via the Push pipeline.

Usage: Configure as a Claude Code PostToolUse hook:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "command": "python3 -m src.ingest.claude_hook \"$FILE_PATH\"",
        "description": "Auto-ingest κ/ψ files into synapse"
      }
    ]
  }
}
```
"""

import asyncio
import hashlib
import logging
import sys
from pathlib import Path

log = logging.getLogger("synapse.claude_hook")


def main():
    """CLI entry point: python3 -m src.ingest.claude_hook <file-path>"""
    if len(sys.argv) < 2:
        log.error("Usage: claude_hook <file-path>")
        sys.exit(1)

    file_path = sys.argv[1]
    asyncio.run(ingest_file(file_path))


async def ingest_file(file_path: str) -> dict | None:
    """Ingest a single file into synapse if it's a κ/ψ vault file.

    Returns the push result dict or None if skipped.
    """
    path = Path(file_path).resolve()

    # Only ingest κ/ or ψ/ files (oracle vault files)
    if not _is_vault_file(path):
        log.debug("Skipping non-vault file: %s", path)
        return None

    if not path.exists():
        log.warning("File not found: %s", path)
        return None

    if not path.is_file():
        return None

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        log.warning("Cannot read %s: %s", path, e)
        return None

    if not content.strip():
        return None

    # Extract metadata from path
    from src.ingest.oracle_paths import extract_metadata
    meta = extract_metadata(str(path), str(path.parent))

    # Resolve source project from path
    source_project = _resolve_source_project(path)

    from src.config import Settings
    from src.db.pg_store import PgStore
    from src.ingest.push import Push
    from src.embed.ollama import OllamaEmbedder

    settings = Settings()
    pg = PgStore(settings)
    await pg.connect()
    await pg.init_schema()

    try:
        embedder = OllamaEmbedder(settings)
    except Exception:
        embedder = None
    pusher = Push(pg, embedder)

    result = await pusher.push_text(
        title=path.stem,
        content=content,
        doc_type=meta.get("doc_type", "note"),
        source_file=str(path),
        source_type="claude_hook",
        source_project=source_project,
        oracle_name=meta.get("oracle_name"),
        metadata=meta.get("metadata"),
        tags=meta.get("tags"),
    )

    await pg.close()
    log.info("Ingested %s → %s", path.name, result.get("status", "?"))
    return result


def _is_vault_file(path: Path) -> bool:
    """Check if path is inside a κ/ or ψ/ vault directory."""
    parts = path.parts
    for part in parts:
        if part in ("κ", "ψ", "kappa", "psi"):
            return True
    return False


def _resolve_source_project(path: Path) -> str:
    """Derive project name from path containing ψ/ or κ/."""
    parts = list(path.parts)
    for i, part in enumerate(parts):
        if part in ("κ", "ψ", "kappa", "psi"):
            # The project is the directory containing κ/ψ
            if i > 0:
                return parts[i - 1]
    return "unknown"


if __name__ == "__main__":
    main()
