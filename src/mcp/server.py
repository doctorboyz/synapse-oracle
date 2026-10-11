"""MCP server — 10 tools for agent-first knowledge access via stdio."""

import asyncio
import json
import logging

import jsonschema

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.config import Settings
from src.db.pg_store import PgStore
from src.embed.ollama import OllamaEmbedder
from src.ingest.push import Push
from src.ingest.oracle_paths import validate_trace_relation
from src.retrieve.hybrid_search import HybridSearch
from src.cache import SearchCache

log = logging.getLogger("synapse.mcp")


def _format_tool_error(tool_name: str, arguments: dict, exc: Exception) -> dict:
    """Error payloads must name the tool and the offending parameter.

    A bare str(e) like 'ambiguous column created_at' gives the calling agent
    no way to tell WHICH tool or parameter failed (ISSUE-009 lesson).
    """
    if isinstance(exc, KeyError):
        missing = exc.args[0] if exc.args else "unknown"
        return {
            "error": f"{tool_name}: missing required parameter '{missing}'",
            "tool": tool_name,
            "parameter": str(missing),
        }
    return {
        "error": f"{tool_name}: {exc}",
        "tool": tool_name,
        "exception_type": type(exc).__name__,
    }


def _validate_tool_input(tool_name: str, arguments: dict) -> dict | None:
    """Validate arguments against the tool's inputSchema.

    Runs inside our handler (SDK validation is disabled) so schema failures
    name the tool as well as the parameter — the SDK's bare "Input
    validation error" leaves the calling agent guessing WHICH tool
    rejected the call (ISSUE-009 lesson). Returns an error payload, or
    None when the arguments are valid.
    """
    tool_def = next((t for t in TOOL_DEFINITIONS if t.name == tool_name), None)
    if tool_def is None:
        return None
    try:
        jsonschema.validate(instance=arguments, schema=tool_def.inputSchema)
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path)
        return {
            "error": f"{tool_name}: invalid arguments — {e.message}",
            "tool": tool_name,
            "parameter": path or None,
        }
    return None

TOOL_DEFINITIONS = [
    Tool(
        name="synapse_search",
        description="Search knowledge vault with hybrid dense+keyword search. Returns ranked results with metadata.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "scope": {"type": "string", "description": "Filter to scope (deprecated — use tags)"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Filter by tags"},
                "doc_type": {"type": "string", "description": "Filter by doc_type"},
                "oracle": {"type": "string", "description": "Filter by oracle name"},
                "source_project": {"type": "string", "description": "Filter by source project"},
                "concepts": {"type": "array", "items": {"type": "string"}, "description": "Filter by concepts"},
                "limit": {"type": "integer", "description": "Max results", "default": 10},
                "mode": {"type": "string", "enum": ["hybrid", "dense", "fts"], "default": "hybrid"},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="synapse_push",
        description="Add knowledge to the vault. Auto-detects oracle metadata from source_file path.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Document title"},
                "content": {"type": "string", "description": "Document content (markdown)"},
                "scope": {"type": "string", "description": "Deprecated — use tags"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for classification (e.g. ['arra', 'python'])"},
                "doc_type": {"type": "string", "default": "learning",
                             "description": "One of: learning, pattern, retro, reference, handoff, protocol, wisdom, instinct, log, note"},
                "source_file": {"type": "string", "description": "Original file path"},
                "source_project": {"type": "string", "description": "Project that sent this knowledge"},
                "concepts": {"type": "array", "items": {"type": "string"}},
                "oracle_name": {"type": "string"},
                "brain_path": {"type": "string"},
                "brain_tier": {"type": "string"},
            },
            "required": ["title", "content"],
        },
    ),
    Tool(
        name="synapse_supersede",
        description="Supersede a document with updated knowledge. Old doc never deleted — marked superseded_by.",
        inputSchema={
            "type": "object",
            "properties": {
                "old_id": {"type": "string", "description": "UUID of document to supersede"},
                "new_content": {"type": "string", "description": "Updated content"},
                "new_title": {"type": "string", "description": "Optional new title"},
                "reason": {"type": "string", "default": "updated"},
            },
            "required": ["old_id", "new_content"],
        },
    ),
    Tool(
        name="synapse_trace",
        description="Create a trace link between two knowledge documents.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "target_id": {"type": "string"},
                "relation": {"type": "string", "enum": ["derived_from", "refines", "contradicts", "extends"]},
                "confidence": {"type": "number", "default": 1.0},
            },
            "required": ["source_id", "target_id", "relation"],
        },
    ),
    Tool(
        name="synapse_trace_chain",
        description="Follow trace chain from a document. Returns all linked documents.",
        inputSchema={
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "direction": {"type": "string", "enum": ["both", "upstream", "downstream"], "default": "both"},
                "max_depth": {"type": "integer", "default": 5},
                "relation": {"type": "string", "description": "Filter to specific relation type"},
            },
            "required": ["doc_id"],
        },
    ),
    Tool(
        name="synapse_concepts",
        description="List or search concepts across the knowledge vault.",
        inputSchema={
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Search concepts by name"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    ),
    Tool(
        name="synapse_get",
        description="Retrieve a full knowledge document by ID, including supersession history.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Document UUID"},
                "include_chain": {"type": "boolean", "default": True},
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="synapse_scope",
        description="List all knowledge scopes with document counts (deprecated — use synapse_tags).",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="synapse_tags",
        description="List or search tags across the knowledge vault with document counts.",
        inputSchema={
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Search tags by name"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    ),
    Tool(
        name="synapse_stats",
        description="Get knowledge vault statistics: total docs, by type, by scope, by oracle.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="synapse_list",
        description="List documents with filters. Returns summaries.",
        inputSchema={
            "type": "object",
            "properties": {
                "scope": {"type": "string", "description": "Filter by scope (deprecated)"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Filter by tags"},
                "doc_type": {"type": "string"},
                "oracle": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
                "order": {"type": "string", "enum": ["newest", "oldest"], "default": "newest"},
            },
        },
    ),
    Tool(
        name="synapse_register",
        description="Register a project with the vault for cross-project search.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Path to the project directory"},
                "project_name": {"type": "string", "description": "Project name (default: auto-detect from path)"},
            },
            "required": ["project_path"],
        },
    ),
    Tool(
        name="synapse_unregister",
        description="Remove a project registration from the vault.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name to unregister"},
            },
            "required": ["project_name"],
        },
    ),
    Tool(
        name="synapse_projects",
        description="List all registered projects and their scopes.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="synapse_search_cross",
        description="Search across multiple scopes, merging results by best score.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "scopes": {"type": "array", "items": {"type": "string"}, "description": "List of scope names to search"},
                "limit": {"type": "integer", "default": 10},
                "mode": {"type": "string", "enum": ["hybrid", "dense", "fts"], "default": "hybrid"},
            },
            "required": ["query", "scopes"],
        },
    ),
    Tool(
        name="synapse_reconcile_log",
        description="View reconcile audit history: when defrag/detox ran, what was merged/fixed, and if it failed. Includes staleness status of the vault.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "description": "Max history entries to return"},
            },
        },
    ),
    Tool(
        name="synapse_fix_doctype",
        description="Fix incorrectly classified doc_types in bulk (e.g. LINE messages auto-classified as 'task' that should be 'note'). Dry-run by default.",
        inputSchema={
            "type": "object",
            "properties": {
                "from_type": {"type": "string", "default": "task", "description": "doc_type to change"},
                "to_type": {"type": "string", "default": "note", "description": "New doc_type"},
                "source_type": {"type": "string", "description": "Only fix docs with this source_type"},
                "dry_run": {"type": "boolean", "default": True, "description": "Report only, change nothing"},
            },
        },
    ),
    Tool(
        name="synapse_write_to_obsidian",
        description="Write Synapse documents to Obsidian vault as .md files with YAML frontmatter and [[wikilinks]]. Use doc_id for a single doc, or query+tags+limit to write search results.",
        inputSchema={
            "type": "object",
            "properties": {
                "doc_id": {"type": "string", "description": "UUID of a single document to write"},
                "query": {"type": "string", "description": "Search query — write top N matching docs"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Filter search by tags"},
                "limit": {"type": "integer", "default": 5, "description": "Max docs when using query mode"},
                "vault_path": {"type": "string", "description": "Path to Obsidian vault root (overrides config)"},
                "subdir": {"type": "string", "description": "Optional subdirectory inside the vault"},
            },
        },
    ),
    Tool(
        name="synapse_ingest_session",
        description="Ingest knowledge from a Claude Code session or any source. Accepts title, content, tags, concepts, and source info. Stores via push pipeline with optional tag rule application.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Document title"},
                "content": {"type": "string", "description": "Document content"},
                "doc_type": {"type": "string", "default": "learning", "description": "Document type: learning, note, task, etc."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for classification and rule activation"},
                "concepts": {"type": "array", "items": {"type": "string"}, "description": "Key concepts"},
                "source_type": {"type": "string", "default": "claude", "description": "Source of the content"},
                "source_project": {"type": "string", "description": "Project or repo name"},
                "oracle_name": {"type": "string", "description": "Oracle name if applicable"},
                "apply_tag_rules": {"type": "boolean", "default": True, "description": "Apply matching tag rules after ingest"},
            },
            "required": ["title", "content"],
        },
    ),
]


async def create_app(settings: Settings | None = None) -> Server:
    settings = settings or Settings()
    pg = PgStore(settings)

    await pg.connect()
    await pg.init_schema()

    embedder = None
    try:
        embedder = OllamaEmbedder(settings)
    except Exception:
        log.warning("Ollama not available, running without embeddings")

    # Shared search cache — invalidated by every Push write
    cache = SearchCache()

    push = Push(pg, embedder, cache=cache)
    search = HybridSearch(pg, embedder, cache=cache)

    server = Server("synapse")

    @server.list_tools()
    async def list_tools():
        return TOOL_DEFINITIONS

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict):
        try:
            validation_error = _validate_tool_input(name, arguments)
            if validation_error:
                return [TextContent(
                    type="text",
                    text=json.dumps(validation_error, default=str),
                )]
            if name == "synapse_search":
                tags = arguments.get("tags") or ([arguments.get("scope")] if arguments.get("scope") else None)
                results = await search.search(
                    query=arguments["query"],
                    doc_type=arguments.get("doc_type"),
                    oracle=arguments.get("oracle"),
                    source_project=arguments.get("source_project"),
                    concepts=arguments.get("concepts"),
                    tags=tags,
                    limit=arguments.get("limit", 10),
                    mode=arguments.get("mode", "hybrid"),
                )
                return [TextContent(type="text", text=json.dumps(results, indent=2))]

            elif name == "synapse_push":
                tags = arguments.get("tags") or ([arguments.get("scope")] if arguments.get("scope") else None)
                result = await push.push_text(
                    title=arguments["title"],
                    content=arguments["content"],
                    doc_type=arguments.get("doc_type", "learning"),
                    source_file=arguments.get("source_file"),
                    source_project=arguments.get("source_project") or arguments.get("scope"),
                    concepts=arguments.get("concepts"),
                    tags=tags,
                    oracle_name=arguments.get("oracle_name"),
                    brain_path=arguments.get("brain_path"),
                    brain_tier=arguments.get("brain_tier"),
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "synapse_supersede":
                # Full pipeline: supersede + clear old embedding + embed new doc
                # (pg.supersede alone left the new doc invisible to dense search)
                result = await push.supersede_and_reindex(
                    old_id=arguments["old_id"],
                    content=arguments["new_content"],
                    reason=arguments.get("reason", "updated"),
                    title=arguments.get("new_title"),
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "synapse_trace":
                validate_trace_relation(arguments["relation"])
                result = await pg.add_trace(
                    source_id=arguments["source_id"],
                    target_id=arguments["target_id"],
                    relation=arguments["relation"],
                    confidence=arguments.get("confidence", 1.0),
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "synapse_trace_chain":
                results = await pg.get_trace_chain(
                    doc_id=arguments["doc_id"],
                    direction=arguments.get("direction", "both"),
                    max_depth=arguments.get("max_depth", 5),
                    relation=arguments.get("relation"),
                )
                return [TextContent(type="text", text=json.dumps(results, indent=2))]

            elif name == "synapse_concepts":
                results = await pg.list_concepts(
                    search=arguments.get("search"),
                    limit=arguments.get("limit", 50),
                )
                return [TextContent(type="text", text=json.dumps(results, indent=2))]

            elif name == "synapse_get":
                doc = await pg.get(
                    doc_id=arguments["id"],
                    include_chain=arguments.get("include_chain", True),
                )
                if doc is None:
                    return [TextContent(type="text", text=json.dumps({"error": "not found"}))]
                return [TextContent(type="text", text=json.dumps(doc, indent=2, default=str))]

            elif name == "synapse_scope":
                scopes = await pg.list_scopes()
                return [TextContent(type="text", text=json.dumps(scopes, indent=2))]

            elif name == "synapse_tags":
                results = await pg.list_tags(
                    search=arguments.get("search"),
                    limit=arguments.get("limit", 50),
                )
                return [TextContent(type="text", text=json.dumps(results, indent=2))]

            elif name == "synapse_stats":
                stats = await pg.stats()
                return [TextContent(type="text", text=json.dumps(stats, indent=2, default=str))]

            elif name == "synapse_list":
                tags = arguments.get("tags") or ([arguments.get("scope")] if arguments.get("scope") else None)
                docs = await pg.list_docs(
                    doc_type=arguments.get("doc_type"),
                    oracle=arguments.get("oracle"),
                    tags=tags,
                    limit=arguments.get("limit", 20),
                    offset=arguments.get("offset", 0),
                    order=arguments.get("order", "newest"),
                )
                return [TextContent(type="text", text=json.dumps(docs, indent=2, default=str))]

            elif name == "synapse_register":
                from src.registry import register_project
                result = await register_project(
                    pg, arguments["project_path"],
                    scope=arguments.get("project_name") or arguments.get("scope"),
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "synapse_unregister":
                from src.registry import unregister_project
                result = await unregister_project(
                    pg, arguments.get("project_name") or arguments.get("scope")
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "synapse_projects":
                from src.registry import list_projects
                result = await list_projects(pg)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "synapse_search_cross":
                results = await search.search_cross_scope(
                    query=arguments["query"],
                    scopes=arguments["scopes"],
                    limit=arguments.get("limit", 10),
                    mode=arguments.get("mode", "hybrid"),
                )
                return [TextContent(type="text", text=json.dumps(results, indent=2))]

            elif name == "synapse_fix_doctype":
                result = await pg.fix_doc_types(
                    from_type=arguments.get("from_type", "task"),
                    to_type=arguments.get("to_type", "note"),
                    source_type=arguments.get("source_type"),
                    dry_run=arguments.get("dry_run", True),
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            elif name == "synapse_reconcile_log":
                logs = await pg.list_reconcile_log(limit=arguments.get("limit", 20))
                staleness = await pg.reconcile_staleness()
                return [TextContent(type="text", text=json.dumps(
                    {"history": logs, "staleness": staleness}, indent=2, default=str))]

            elif name == "synapse_write_to_obsidian":
                from pathlib import Path
                from src.ingest.obsidian_writer import write_document_to_obsidian, write_search_results_to_obsidian

                vault_path = arguments.get("vault_path") or settings.obsidian_vault_path
                if not vault_path:
                    return [TextContent(type="text", text=json.dumps(
                        {"error": "No vault_path provided and OBSIDIAN_VAULT_PATH not configured"}))]
                if not Path(vault_path).exists():
                    return [TextContent(type="text", text=json.dumps(
                        {"error": f"Vault path does not exist: {vault_path}"}))]

                subdir = arguments.get("subdir", "")
                doc_id = arguments.get("doc_id")

                if doc_id:
                    result = await write_document_to_obsidian(pg, doc_id, vault_path, subdir)
                elif arguments.get("query"):
                    results = await search.search(
                        query=arguments["query"],
                        tags=arguments.get("tags"),
                        limit=arguments.get("limit", 5),
                        mode="hybrid",
                    )
                    result = await write_search_results_to_obsidian(pg, results, vault_path, subdir)
                else:
                    return [TextContent(type="text", text=json.dumps(
                        {"error": "Provide doc_id or query"}))]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "synapse_ingest_session":
                result = await push.push_text(
                    title=arguments["title"],
                    content=arguments["content"],
                    doc_type=arguments.get("doc_type", "learning"),
                    source_type=arguments.get("source_type", "claude"),
                    source_project=arguments.get("source_project"),
                    oracle_name=arguments.get("oracle_name"),
                    tags=arguments.get("tags"),
                    concepts=arguments.get("concepts"),
                )
                # Apply tag rules if requested
                doc_id = result.get("id", "")
                tags = arguments.get("tags", [])
                if doc_id and tags and arguments.get("apply_tag_rules", True):
                    try:
                        from src.assistant.tag_rules import apply_tag_rules
                        actions = await apply_tag_rules(
                            pg, doc_id, tags, content=arguments["content"],
                        )
                        result["tag_rule_actions"] = actions
                    except Exception as e:
                        log.warning("Tag rules failed for ingest_session: %s", e)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            else:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        except Exception as e:
            log.error("Tool %s error: %s", name, e)
            return [TextContent(type="text", text=json.dumps(
                _format_tool_error(name, arguments, e), default=str))]

    return server


async def run_server():
    app = await create_app()
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run_server())