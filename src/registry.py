"""Project registry — PostgreSQL-backed project registration for cross-project search."""

import json
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.db.pg_store import PgStore

log = logging.getLogger("synapse.registry")

PROJECT_PATTERNS = [
    re.compile(r"/github\.com/[^/]+/([^/]+)/"),
    re.compile(r"/Code/([^/]+)/"),
]

DEFAULT_BACKUP_PATH = Path.home() / ".synapse" / "projects.json"


def detect_project_name(project_path: str) -> str:
    """Auto-detect project name from path. Returns last directory component, sanitized."""
    path = Path(project_path).resolve()
    name = path.name.lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name or "shared"


def validate_project_name(name: str) -> bool:
    """Validate project name: lowercase, alphanumeric, dashes only, 1-64 chars."""
    return bool(re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", name))


# Backward compat aliases
detect_scope = detect_project_name
validate_scope = validate_project_name


async def register_project(pg: PgStore, project_path: str, scope: str | None = None) -> dict:
    """Register a project with the vault. Auto-detect project name if not provided."""
    project_name = scope or detect_project_name(project_path)

    if not validate_project_name(project_name):
        raise ValueError(f"Invalid project name: {project_name}")

    async with pg.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO registered_projects (scope, project_path, registered_at)
               VALUES ($1, $2, NOW())
               ON CONFLICT (scope) DO UPDATE SET project_path = $2, registered_at = NOW()
            """,
            project_name, str(Path(project_path).resolve()),
        )

    result = {"project_name": project_name, "project_path": project_path, "status": "registered"}
    await _save_registry_backup(pg)
    return result


async def unregister_project(pg: PgStore, scope: str) -> dict:
    """Remove a project registration."""
    async with pg.pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM registered_projects WHERE scope = $1", scope
        )
    deleted = "DELETE 1" in result
    if deleted:
        await _save_registry_backup(pg)
    return {"project_name": scope, "status": "unregistered" if deleted else "not_found"}


async def list_projects(pg: PgStore) -> list[dict]:
    """List all registered projects."""
    async with pg.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT scope, project_path, registered_at FROM registered_projects ORDER BY scope"
        )
    return [
        {"project_name": r["scope"], "project_path": r["project_path"], "registered_at": str(r["registered_at"])}
        for r in rows
    ]


async def get_all_project_names(pg: PgStore) -> list[str]:
    """Get all registered project names."""
    async with pg.pool.acquire() as conn:
        rows = await conn.fetch("SELECT scope FROM registered_projects ORDER BY scope")
    return [r["scope"] for r in rows]


# Backward compat alias
get_all_scopes = get_all_project_names


# ─── Backup / Restore ────────────────────────────────────────────────────

async def _save_registry_backup(pg: PgStore, path: Path | None = None) -> None:
    """Save registered projects to JSON backup file."""
    if path is None:
        path = DEFAULT_BACKUP_PATH
    try:
        projects = await list_projects(pg)
        data = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "projects": projects,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        log.info("Registry backup saved to %s (%d projects)", path, len(projects))
    except Exception as e:
        log.warning("Failed to save registry backup: %s", e)


async def restore_registry_backup(pg: PgStore, path: Path | None = None) -> dict:
    """Restore registered projects from JSON backup if DB is empty.

    Returns {restored: int, skipped: int, errors: int}
    """
    if path is None:
        path = DEFAULT_BACKUP_PATH

    if not path.exists():
        log.debug("No registry backup found at %s", path)
        return {"restored": 0, "skipped": 0, "errors": 0, "reason": "no_backup"}

    # Check if DB already has projects
    existing = await list_projects(pg)
    if existing:
        log.info("DB already has %d projects, skipping restore", len(existing))
        return {"restored": 0, "skipped": len(existing), "errors": 0, "reason": "db_not_empty"}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        projects = data.get("projects", [])
    except Exception as e:
        log.warning("Failed to read registry backup: %s", e)
        return {"restored": 0, "skipped": 0, "errors": 1, "reason": "read_error"}

    restored = 0
    errors = 0
    for p in projects:
        scope = p.get("scope")
        project_path = p.get("project_path")
        if not scope or not project_path:
            errors += 1
            continue
        try:
            # Validate path still exists
            if not Path(project_path).exists():
                log.warning("Project path no longer exists, skipping: %s", project_path)
                errors += 1
                continue
            await register_project(pg, project_path, scope=scope)
            restored += 1
        except Exception as e:
            log.warning("Failed to restore project %s: %s", scope, e)
            errors += 1

    log.info("Registry restore complete: restored=%d, errors=%d", restored, errors)
    return {"restored": restored, "skipped": 0, "errors": errors}
