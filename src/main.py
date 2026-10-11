"""synapse — FastAPI app + CLI entry point."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from src.api.routes import init_routes, router
from src.config import Settings
from src.db.pg_store import PgStore
from src.embed.ollama import OllamaEmbedder

log = logging.getLogger("synapse")

_pg: PgStore | None = None
_scheduler = None

app = FastAPI(title="synapse", version="4.0.0",
              description="Agent-first knowledge service for the Oracle ecosystem")
app.include_router(router)


async def _do_shutdown() -> None:
    """Graceful shutdown triggered by SIGTERM/SIGINT."""
    global _scheduler, _pg
    log.info("Shutting down gracefully...")
    if _scheduler:
        await _scheduler.stop()
    if _pg:
        await _pg.close()
    from src.daemon import remove_pid
    remove_pid()
    log.info("Shutdown complete")


@app.on_event("startup")
async def startup():
    global _pg, _scheduler

    settings = Settings()

    from src.daemon import write_pid, setup_signals
    write_pid(settings.daemon_pid_file)

    def _on_shutdown():
        asyncio.create_task(_do_shutdown())

    def _on_reload():
        settings.reload()

    setup_signals(on_reload=_on_reload, on_shutdown=_on_shutdown)

    _pg = PgStore(settings)
    await _pg.connect()
    await _pg.init_schema()

    # Seed default tag rules (idempotent)
    from src.assistant.tag_rules import seed_default_rules
    await seed_default_rules(_pg)

    from src.registry import restore_registry_backup
    await restore_registry_backup(_pg)

    embedder = None
    try:
        embedder = OllamaEmbedder(settings)
    except Exception:
        log.warning("Ollama not available, running without embeddings")
        embedder = None

    init_routes(_pg, embedder, settings=settings)

    if settings.scan_interval > 0 or settings.reconcile_hour >= 0 or settings.topic_monitor_interval > 0:
        from src.scheduler import TaskScheduler
        _scheduler = TaskScheduler(
            pg=_pg,
            settings=settings,
            embedder=embedder,
            scan_interval=settings.scan_interval,
            reconcile_hour=settings.reconcile_hour,
            topic_monitor_interval=settings.topic_monitor_interval,
        )
        await _scheduler.start()


@app.on_event("shutdown")
async def shutdown():
    await _do_shutdown()


# ─── CLI command implementations ──────────────────────────────────────

async def _cmd_push(args):
    from src.cli import get_components, cleanup, output

    tags = _parse_list(args.tags) or ([args.scope] if args.scope and args.scope != "shared" else None)
    components = await get_components()
    try:
        if args.file:
            result = await components.push.push_file(
                file_path=args.file,
                tags=tags,
                doc_type=args.doc_type,
            )
        else:
            if not args.title:
                print(json_dump({"error": "--title is required when not using --file"}))
                sys.exit(1)
            if not args.content:
                print(json_dump({"error": "--content is required when not using --file"}))
                sys.exit(1)

            result = await components.push.push_text(
                title=args.title,
                content=args.content,
                doc_type=args.doc_type or "learning",
                source_file=args.source_file,
                source_project=args.source_project or args.scope,
                concepts=_parse_list(args.concepts),
                tags=tags,
                oracle_name=args.oracle_name,
                brain_path=args.brain_path,
                brain_tier=args.brain_tier,
            )
        output(result)
    finally:
        await cleanup(components)


async def _cmd_search(args):
    from src.cli import get_components, cleanup, output

    tags = _parse_list(args.tags) or ([args.scope] if args.scope else None)
    components = await get_components()
    try:
        results = await components.search.search(
            query=args.query,
            doc_type=args.doc_type,
            oracle=args.oracle,
            source_project=args.source_project,
            concepts=_parse_list(args.concepts),
            tags=tags,
            limit=args.limit,
            mode=args.mode,
        )
        output(results)
    finally:
        await cleanup(components)


async def _cmd_get(args):
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        doc = await components.pg.get(
            doc_id=args.id,
            include_chain=not args.no_chain,
        )
        if doc is None:
            output({"error": "not found", "id": args.id})
            sys.exit(1)
        output(doc)
    finally:
        await cleanup(components)


async def _cmd_list(args):
    from src.cli import get_components, cleanup, output

    tags = _parse_list(args.tags) or ([args.scope] if args.scope else None)
    components = await get_components()
    try:
        docs = await components.pg.list_docs(
            doc_type=args.doc_type,
            oracle=args.oracle,
            tags=tags,
            limit=args.limit,
            offset=args.offset,
            order=args.order,
        )
        output(docs)
    finally:
        await cleanup(components)


async def _cmd_scope(args):
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        scopes = await components.pg.list_scopes()
        output(scopes)
    finally:
        await cleanup(components)


async def _cmd_tags(args):
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        result = await components.pg.list_tags(
            search=args.search,
            limit=args.limit,
        )
        output(result)
    finally:
        await cleanup(components)


async def _cmd_stats(args):
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        stats = await components.pg.stats()
        output(stats)
    finally:
        await cleanup(components)


async def _cmd_supersede(args):
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        # Full pipeline: supersede + clear old embedding + embed new doc.
        # Calling pg.supersede directly left the new doc unfindable via
        # dense search (audit 11/10/26 — stored knowledge went silent).
        result = await components.push.supersede_and_reindex(
            old_id=args.old_id,
            content=args.new_content,
            reason=args.reason,
            title=args.new_title,
        )
        output(result)
    finally:
        await cleanup(components)


async def _cmd_trace(args):
    from src.cli import get_components, cleanup, output
    from src.ingest.oracle_paths import validate_trace_relation

    validate_trace_relation(args.relation)
    components = await get_components()
    try:
        result = await components.pg.add_trace(
            source_id=args.source,
            target_id=args.target,
            relation=args.relation,
            confidence=args.confidence,
        )
        output(result)
    finally:
        await cleanup(components)


async def _cmd_trace_chain(args):
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        results = await components.pg.get_trace_chain(
            doc_id=args.doc_id,
            direction=args.direction,
            max_depth=args.max_depth,
        )
        output(results)
    finally:
        await cleanup(components)


async def _cmd_concepts(args):
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        results = await components.pg.list_concepts(
            search=args.search,
            limit=args.limit,
        )
        output(results)
    finally:
        await cleanup(components)


async def _cmd_init(args):
    from src.ingest.init_scan import init_scan
    from src.cli import output

    tags = _parse_list(args.tags) or ([args.scope] if args.scope else None)
    result = await init_scan(
        path=args.path,
        tags=tags,
        dry_run=args.dry_run,
    )
    output(result)


async def _cmd_reconcile(args):
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        if args.history:
            logs = await components.pg.list_reconcile_log(limit=args.limit)
            output({"history": logs})
            return

        from src.reconcile import reconcile
        log_entry = await components.pg.start_reconcile_log(scope=args.scope, dry_run=args.dry_run)
        log_id = log_entry["id"]

        try:
            result = await reconcile(
                pg=components.pg,
                embedder=components.embedder,
                settings=components.settings,
                scope=args.scope,
                cross_scope=args.cross_scope,
                dry_run=args.dry_run,
            )
            defrag = result.get("defrag", {})
            detox = result.get("detox", {})
            await components.pg.complete_reconcile_log(
                log_id=log_id,
                merged_duplicates=defrag.get("merged_duplicates", 0),
                removed_duplicates=defrag.get("removed_duplicates", 0),
                conflicts_found=detox.get("conflicts_found", 0),
                conflicts_resolved=detox.get("conflicts_resolved", 0),
                status="completed",
            )
        except Exception as e:
            await components.pg.complete_reconcile_log(
                log_id=log_id,
                status="failed",
                error_message=str(e)[:500],
            )
            raise

        output(result)
    finally:
        await cleanup(components)


async def _cmd_register(args):
    from src.registry import register_project
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        result = await register_project(components.pg, args.path, scope=args.scope)
        output(result)
    finally:
        await cleanup(components)


async def _cmd_unregister(args):
    from src.registry import unregister_project
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        result = await unregister_project(components.pg, args.scope)
        output(result)
    finally:
        await cleanup(components)


async def _cmd_projects(args):
    from src.registry import list_projects
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        result = await list_projects(components.pg)
        output(result)
    finally:
        await cleanup(components)


async def _cmd_search_cross(args):
    from src.cli import get_components, cleanup, output

    scopes = _parse_list(args.scopes) or []
    if not scopes:
        print(json_dump({"error": "--scopes is required (comma-separated)"}))
        sys.exit(1)

    components = await get_components()
    try:
        results = await components.search.search_cross_scope(
            query=args.query,
            scopes=scopes,
            limit=args.limit,
            mode=args.mode,
        )
        output(results)
    finally:
        await cleanup(components)


async def _cmd_stop(args):
    from src.daemon import stop_daemon, get_status
    from src.cli import output

    status = get_status(args.pid_file)
    if not status["running"]:
        output({"status": "not_running", "message": "No daemon running"})
        return
    result = stop_daemon(args.pid_file)
    output(result)


async def _cmd_status(args):
    from src.daemon import get_status
    from src.local_only import check_and_warn
    from src.cli import get_components, cleanup, output

    result = get_status(args.pid_file)
    settings = Settings()

    violations = check_and_warn(settings, allow_docker=(settings.api_host == "0.0.0.0"))
    result["local_only_violations"] = violations

    try:
        components = await get_components()
        stats = await components.pg.stats()
        result["database"] = stats
        scopes = await components.pg.list_scopes()
        result["scopes"] = len(scopes)
        await cleanup(components)
    except Exception as e:
        result["database"] = {"error": str(e)}

    output(result)


async def _cmd_scan(args):
    from src.scheduler import TaskScheduler
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        scheduler = TaskScheduler(components.pg, components.settings)
        result = await scheduler.scan_once()
        output(result)
    finally:
        await cleanup(components)


async def _cmd_install_hooks(args):
    from src.hooks.installer import install_hooks
    from src.cli import output

    result = install_hooks(
        settings_path=Path(args.settings_path) if args.settings_path else None,
        python_path=args.python_path,
        script_path=args.script_path,
        dry_run=args.dry_run,
    )
    output(result)


async def _cmd_topic_add(args):
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        result = await components.pg.add_search_topic(
            scope=args.scope,
            topic=args.topic,
            source=args.source,
            frequency=args.frequency,
        )
        output(result)
    finally:
        await cleanup(components)


async def _cmd_topic_list(args):
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        result = await components.pg.list_search_topics(
            scope=args.scope,
            enabled_only=args.enabled_only,
        )
        output(result)
    finally:
        await cleanup(components)


async def _cmd_topic_remove(args):
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        result = await components.pg.remove_search_topic(args.topic_id)
        output(result)
    finally:
        await cleanup(components)


async def _cmd_topic_run(args):
    from src.cli import get_components, cleanup, output
    from src.connectors.topic_monitor import run_topic_monitor
    from src.connectors.web_search import WebSearchConnector
    from src.connectors.social_search import SocialSearchConnector

    components = await get_components()
    try:
        stats = await run_topic_monitor(
            components.pg,
            components.push,
            web_search=WebSearchConnector(components.settings),
            social_search=SocialSearchConnector(components.settings),
            limit_per_topic=args.limit,
        )
        output(stats)
    finally:
        await cleanup(components)


# ─── Helpers ────────────────────────────────────────────────────────────

def _parse_list(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def json_dump(data) -> str:
    import json
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)


# ─── CLI argument parser ───────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synapse", description="Synapse — Knowledge Framework v4")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="Start HTTP API server")
    sub.add_parser("mcp", help="Start MCP stdio server")

    p = sub.add_parser("push", help="Add knowledge to vault")
    p.add_argument("--title", help="Document title (required unless --file)")
    p.add_argument("--content", help="Document content (required unless --file)")
    p.add_argument("--file", "-f", help="File path to ingest")
    p.add_argument("--scope", help="Scope/namespace (deprecated — use --tags)")
    p.add_argument("--tags", help="Comma-separated tags for classification")
    p.add_argument("--doc-type", default="learning", help="Document type")
    p.add_argument("--source-file", help="Original source file path")
    p.add_argument("--source-project", help="Project that sent this knowledge")
    p.add_argument("--concepts", help="Comma-separated concepts")
    p.add_argument("--oracle-name", help="Oracle name")
    p.add_argument("--brain-path", help="Brain path (κ/ψ relative)")
    p.add_argument("--brain-tier", help="Brain tier (intrinsic/extrinsic)")

    p = sub.add_parser("search", help="Search knowledge vault")
    p.add_argument("query", help="Search query")
    p.add_argument("--scope", help="Filter by scope (deprecated — use --tags)")
    p.add_argument("--tags", help="Comma-separated tags filter")
    p.add_argument("--doc-type", help="Filter by doc_type")
    p.add_argument("--oracle", help="Filter by oracle name")
    p.add_argument("--source-project", help="Filter by source project")
    p.add_argument("--concepts", help="Comma-separated concepts filter")
    p.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p.add_argument("--mode", default="hybrid", choices=["hybrid", "dense", "fts"], help="Search mode")

    p = sub.add_parser("get", help="Retrieve full document by ID")
    p.add_argument("id", help="Document UUID")
    p.add_argument("--no-chain", action="store_true", help="Don't include supersession chain")

    p = sub.add_parser("list", help="List documents with filters")
    p.add_argument("--scope", help="Filter by scope (deprecated — use --tags)")
    p.add_argument("--tags", help="Comma-separated tags filter")
    p.add_argument("--doc-type", help="Filter by doc_type")
    p.add_argument("--oracle", help="Filter by oracle name")
    p.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    p.add_argument("--offset", type=int, default=0, help="Offset for pagination")
    p.add_argument("--order", default="newest", choices=["newest", "oldest"], help="Sort order")

    sub.add_parser("scope", help="List all knowledge scopes (deprecated — use tags)")
    p = sub.add_parser("tags", help="List or search tags across the knowledge vault")
    p.add_argument("--search", help="Search tags by name")
    p.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")

    sub.add_parser("stats", help="Show knowledge vault statistics")

    p = sub.add_parser("supersede", help="Supersede a document with updated content")
    p.add_argument("old_id", help="UUID of document to supersede")
    p.add_argument("--new-content", required=True, help="Updated content")
    p.add_argument("--new-title", help="Optional new title")
    p.add_argument("--reason", default="updated", help="Reason for supersession")

    p = sub.add_parser("trace", help="Create a trace link between documents")
    p.add_argument("--source", required=True, help="Source document UUID")
    p.add_argument("--target", required=True, help="Target document UUID")
    p.add_argument("--relation", required=True,
                   choices=["derived_from", "refines", "contradicts", "extends"],
                   help="Relation type")
    p.add_argument("--confidence", type=float, default=1.0, help="Confidence score (0-1)")

    p = sub.add_parser("trace-chain", help="Follow trace chain from a document")
    p.add_argument("doc_id", help="Document UUID")
    p.add_argument("--direction", default="both", choices=["both", "upstream", "downstream"],
                   help="Trace direction")
    p.add_argument("--max-depth", type=int, default=5, help="Max trace depth")

    p = sub.add_parser("concepts", help="List or search concepts")
    p.add_argument("--search", help="Search concepts by name")
    p.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")

    p = sub.add_parser("init", help="Scan files and build initial knowledge vault")
    p.add_argument("--path", default=".", help="Directory to scan (default: current)")
    p.add_argument("--scope", help="Scope for ingested documents (deprecated — use --tags)")
    p.add_argument("--tags", help="Comma-separated tags for ingested documents")
    p.add_argument("--dry-run", action="store_true", help="Show what would be ingested without ingesting")

    p = sub.add_parser("reconcile", help="Defrag duplicates + detect/fix conflicts")
    p.add_argument("--scope", help="Limit to a specific scope")
    p.add_argument("--cross-scope", action="store_true", help="Search across all scopes for duplicates/conflicts")
    p.add_argument("--dry-run", action="store_true", help="Show what would be changed without changing")
    p.add_argument("--history", action="store_true", help="Show recent reconcile runs instead of running")
    p.add_argument("--limit", type=int, default=20, help="Max history entries (default: 20)")

    p = sub.add_parser("register", help="Register a project with the vault")
    p.add_argument("--path", default=".", help="Project directory (default: current)")
    p.add_argument("--scope", help="Scope name (default: auto-detect from path)")

    p = sub.add_parser("unregister", help="Remove a project registration")
    p.add_argument("scope", help="Scope name to unregister")

    sub.add_parser("projects", help="List registered projects")

    p = sub.add_parser("search-cross", help="Search across multiple scopes")
    p.add_argument("query", help="Search query")
    p.add_argument("--scopes", required=True, help="Comma-separated scope names")
    p.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p.add_argument("--mode", default="hybrid", choices=["hybrid", "dense", "fts"], help="Search mode")

    p = sub.add_parser("stop", help="Stop a running synapse daemon")
    p.add_argument("--pid-file", help="Path to PID file")

    p = sub.add_parser("status", help="Show daemon and system status")
    p.add_argument("--pid-file", help="Path to PID file")

    sub.add_parser("scan", help="Scan all registered projects for new files")

    p = sub.add_parser("install-hooks", help="Register synapse hooks in ~/.claude/settings.json")
    p.add_argument("--dry-run", action="store_true", help="Show what would be installed without making changes")
    p.add_argument("--python-path", help="Path to Python interpreter (default: current)")
    p.add_argument("--script-path", help="Path to context injection script")
    p.add_argument("--settings-path", help="Path to settings.json (default: ~/.claude/settings.json)")

    p = sub.add_parser("topic-add", help="Add a search topic for web/social monitoring")
    p.add_argument("--scope", required=True, help="Scope to associate topic with")
    p.add_argument("--topic", required=True, help="Search query/topic")
    p.add_argument("--source", default="web", choices=["web", "twitter", "reddit", "hackernews"],
                   help="Source platform (default: web)")
    p.add_argument("--frequency", default="daily", choices=["hourly", "daily", "weekly"],
                   help="Monitoring frequency (default: daily)")

    p = sub.add_parser("topic-list", help="List configured search topics")
    p.add_argument("--scope", help="Filter by scope")
    p.add_argument("--enabled-only", action="store_true", help="Show only enabled topics")

    p = sub.add_parser("topic-remove", help="Remove a search topic")
    p.add_argument("topic_id", help="Topic UUID")

    p = sub.add_parser("topic-run", help="Manually run topic monitor")
    p.add_argument("--limit", type=int, default=5, help="Results per topic (default: 5)")

    p = sub.add_parser("fix-doctype", help="Fix incorrectly classified doc_types")
    p.add_argument("--from-type", default="task", help="Source doc_type to change (default: task)")
    p.add_argument("--to-type", default="note", help="Target doc_type (default: note)")
    p.add_argument("--source-type", default=None, help="Only fix docs with this source_type")
    p.add_argument("--apply", action="store_true", default=False, help="Apply changes (default: dry-run)")

    return parser



async def _cmd_fix_doctype(args):
    from src.cli import get_components, cleanup, output

    components = await get_components()
    try:
        result = await components.pg.fix_doc_types(
            from_type=args.from_type,
            to_type=args.to_type,
            source_type=args.source_type if args.source_type else None,
            dry_run=not args.apply,
        )
        output(result)
    finally:
        await cleanup(components)


COMMAND_DISPATCH = {
    "serve": None,
    "mcp": None,
    "push": _cmd_push,
    "search": _cmd_search,
    "get": _cmd_get,
    "list": _cmd_list,
    "scope": _cmd_scope,
    "tags": _cmd_tags,
    "stats": _cmd_stats,
    "supersede": _cmd_supersede,
    "trace": _cmd_trace,
    "trace-chain": _cmd_trace_chain,
    "concepts": _cmd_concepts,
    "init": _cmd_init,
    "reconcile": _cmd_reconcile,
    "register": _cmd_register,
    "unregister": _cmd_unregister,
    "projects": _cmd_projects,
    "search-cross": _cmd_search_cross,
    "stop": _cmd_stop,
    "status": _cmd_status,
    "scan": _cmd_scan,
    "install-hooks": _cmd_install_hooks,
    "topic-add": _cmd_topic_add,
    "topic-list": _cmd_topic_list,
    "topic-remove": _cmd_topic_remove,
    "fix-doctype": _cmd_fix_doctype,
    "topic-run": _cmd_topic_run,
}


def cli_main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "serve":
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        )
        settings = Settings()
        uvicorn.run(app, host=settings.api_host, port=settings.api_port)
    elif args.command == "mcp":
        from src.mcp.server import run_server
        asyncio.run(run_server())
    elif args.command in COMMAND_DISPATCH and COMMAND_DISPATCH[args.command]:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        handler = COMMAND_DISPATCH[args.command]
        asyncio.run(handler(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    cli_main()
