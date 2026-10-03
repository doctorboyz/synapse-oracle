"""Obsidian Writer — write Synapse documents to Obsidian vault as .md files.

Produces Obsidian-compatible markdown with YAML frontmatter and [[wikilinks]]
connecting related documents. Synapse is the brain; Obsidian is the interface.
"""

import logging
import re
from pathlib import Path

from src.db.pg_store import PgStore

log = logging.getLogger("synapse.obsidian_writer")

FRONTMATTER_FIELDS = ["tags", "concepts", "source", "synapse_doc_id",
                       "created_at", "oracle_name", "doc_type", "source_project"]


def sanitize_filename(title: str, doc_id: str = "") -> str:
    """Convert a title to a safe filename. Uses doc_id[:8] suffix to avoid collisions."""
    name = title.lower().strip()
    name = re.sub(r"[^a-z0-9ก-๙\s\-_]", "", name)
    name = re.sub(r"\s+", "-", name)
    name = name[:80]
    suffix = f"-{doc_id[:8]}" if doc_id else ""
    return f"{name}{suffix}.md"


def _to_yaml_value(val) -> str:
    """Serialize a value for YAML frontmatter."""
    if isinstance(val, list):
        return "[" + ", ".join(repr(v) for v in val) + "]"
    if val is None:
        return ""
    return str(val)


def _build_frontmatter(doc: dict) -> str:
    """Build YAML frontmatter block from document fields."""
    lines = ["---"]
    for field in FRONTMATTER_FIELDS:
        val = doc.get(field)
        if val is not None and val != "" and val != []:
            lines.append(f"{field}: {_to_yaml_value(val)}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _build_wikilinks(related_docs: list[dict], exclude_id: str) -> list[str]:
    """Build [[wikilinks]] from related document titles, deduplicated."""
    links = []
    seen = set()
    for rel in related_docs:
        rid = rel.get("id", "")
        if rid == exclude_id:
            continue
        title = rel.get("title", "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        links.append(f"- [[{title}]]")
    return links


async def write_document_to_obsidian(
    pg: PgStore,
    doc_id: str,
    vault_path: str,
    subdir: str = "",
) -> dict:
    """Write a single Synapse document as .md to an Obsidian vault.

    Args:
        pg: PgStore connection
        doc_id: UUID of the document to write
        vault_path: Path to the Obsidian vault root
        subdir: Optional subdirectory inside the vault

    Returns:
        {"file": str, "doc_id": str, "title": str, "links": int}
    """
    doc = await pg.get(doc_id, include_chain=False)
    if not doc:
        return {"error": f"Document not found: {doc_id}"}

    title = doc.get("title", f"untitled-{doc_id[:8]}")
    content = doc.get("content", "")
    tags = doc.get("tags", [])
    concepts = doc.get("concepts", [])
    created_at = doc.get("created_at", "")
    oracle_name = doc.get("oracle_name", "")
    doc_type = doc.get("doc_type", "note")
    source_project = doc.get("source_project", "")

    # Get related documents via trace links
    try:
        traces = await pg.get_trace_chain(doc_id, direction="both", max_depth=1)
    except Exception as e:
        log.warning("Failed to get traces for %s: %s", doc_id, e)
        traces = []

    wikilinks = _build_wikilinks(traces, doc_id)
    related_section = "\n".join(wikilinks) if wikilinks else "No related notes found."

    # Build markdown
    frontmatter = _build_frontmatter({
        "tags": tags,
        "concepts": concepts,
        "source": "synapse",
        "synapse_doc_id": doc_id,
        "created_at": str(created_at) if created_at else "",
        "oracle_name": oracle_name,
        "doc_type": doc_type,
        "source_project": source_project,
    })

    body = f"# {title}\n\n{content}\n\n## Related Notes\n\n{related_section}\n"
    md_content = frontmatter + body

    # Write file
    vault = Path(vault_path).resolve()
    if subdir:
        vault = vault / subdir
    vault.mkdir(parents=True, exist_ok=True)

    filename = sanitize_filename(title, doc_id)
    # Avoid filename collisions
    out_path = vault / filename
    counter = 1
    while out_path.exists():
        stem = filename.rsplit(".", 1)[0]
        out_path = vault / f"{stem}-{counter}.md"
        counter += 1

    out_path.write_text(md_content, encoding="utf-8")
    log.info("Wrote %s to %s", title, out_path)

    return {
        "file": str(out_path),
        "doc_id": doc_id,
        "title": title,
        "links": len(wikilinks),
    }


async def write_search_results_to_obsidian(
    pg: PgStore,
    docs: list[dict],
    vault_path: str,
    subdir: str = "",
) -> dict:
    """Write search result documents to Obsidian vault.

    Args:
        pg: PgStore connection
        docs: List of document dicts from search results (must have 'id')
        vault_path: Path to the Obsidian vault root
        subdir: Optional subdirectory inside the vault

    Returns:
        {"written": int, "files": list[str]}
    """
    files = []
    for doc in docs:
        doc_id = doc.get("id")
        if not doc_id:
            continue
        result = await write_document_to_obsidian(pg, doc_id, vault_path, subdir)
        if "error" not in result:
            files.append(result["file"])
        else:
            log.warning("Failed to write %s: %s", doc_id, result["error"])

    return {"written": len(files), "files": files}
