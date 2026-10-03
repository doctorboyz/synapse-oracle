"""Obsidian-style link parsing — [[Link Title]] and [[Link Title|Display]]."""

import re
import logging

log = logging.getLogger("synapse.obsidian_links")

OBSIDIAN_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def extract_links(content: str) -> list[dict]:
    """Extract all Obsidian-style links from content.

    Returns list of dicts: {target, display, raw}
    - target: the link target (what to search for)
    - display: display text if pipe syntax used, else None
    - raw: the full matched string e.g. "[[Link|Display]]"
    """
    links = []
    for m in OBSIDIAN_LINK_RE.finditer(content):
        target = m.group(1).strip()
        display = m.group(2)
        if display:
            display = display.strip()
        links.append({
            "target": target,
            "display": display or None,
            "raw": m.group(0),
        })
    return links


def replace_links(content: str, resolver: dict[str, str]) -> str:
    """Replace Obsidian links with markdown links using resolved IDs.

    resolver: dict mapping target title -> doc_id
    Returns updated content with [[Title]] replaced by [Title](/documents/{id})
    """
    def _repl(m):
        target = m.group(1).strip()
        display = m.group(2)
        label = (display or target).strip()
        doc_id = resolver.get(target)
        if doc_id:
            return f"[{label}](/documents/{doc_id})"
        return f"[{label}]"  # unresolved — keep as plain bracket text
    return OBSIDIAN_LINK_RE.sub(_repl, content)


async def resolve_links(pg, links: list[dict], tags: list[str] | None = None,
                      exclude_id: str | None = None) -> dict[str, str]:
    """Resolve link targets to document IDs.

    Searches across all documents first, then falls back to same tags.
    Excludes the current document to avoid self-references.
    Returns {target_title: doc_id} for resolved links.
    """
    resolved = {}
    targets = {link["target"] for link in links}

    for target in targets:
        # 1. Exact title match across all scopes (best match)
        try:
            async with pg.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT id FROM knowledge_documents
                       WHERE title = $1 AND superseded_by IS NULL
                       LIMIT 1""",
                    target,
                )
                if row and str(row["id"]) != exclude_id:
                    resolved[target] = str(row["id"])
                    continue
        except Exception:
            pass

        # 2. Case-insensitive exact title match across all scopes
        try:
            async with pg.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT id FROM knowledge_documents
                       WHERE lower(title) = lower($1) AND superseded_by IS NULL
                       LIMIT 1""",
                    target,
                )
                if row and str(row["id"]) != exclude_id:
                    resolved[target] = str(row["id"])
                    continue
        except Exception:
            pass

        # 3. Match against source_file (for path-based links like [[path/to/File]])
        try:
            async with pg.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT id FROM knowledge_documents
                       WHERE source_file = $1 AND superseded_by IS NULL
                       LIMIT 1""",
                    target,
                )
                if row and str(row["id"]) != exclude_id:
                    resolved[target] = str(row["id"])
                    continue
                # Substring match in source_file path
                row = await conn.fetchrow(
                    """SELECT id FROM knowledge_documents
                       WHERE source_file ILIKE $1 AND superseded_by IS NULL
                       LIMIT 1""",
                    f"%{target}%",
                )
                if row and str(row["id"]) != exclude_id:
                    resolved[target] = str(row["id"])
                    continue
        except Exception:
            pass

        # 4. Exact title match filtered by same tags
        try:
            docs = await pg.list_docs(tags=tags, limit=20)
            for doc in docs:
                if str(doc.get("id")) == exclude_id:
                    continue
                if doc.get("title", "").lower() == target.lower():
                    resolved[target] = doc["id"]
                    break
            else:
                # 5. Fallback: FTS search across all scopes
                results = await pg.search_fts(query=target, limit=5)
                for r in results:
                    if str(r.get("id")) != exclude_id:
                        resolved[target] = r["id"]
                        break
        except Exception as e:
            log.warning("Failed to resolve link '%s': %s", target, e)

    return resolved


async def create_traces_from_links(pg, doc_id: str, content: str,
                                    tags: list[str] | None = None) -> dict:
    """Parse Obsidian links in content and create trace links to referenced docs.

    Returns dict with: links_found, traces_created, unresolved
    """
    links = extract_links(content)
    if not links:
        return {"links_found": 0, "traces_created": 0, "unresolved": []}

    resolved = await resolve_links(pg, links, tags=tags, exclude_id=doc_id)
    traces_created = 0
    unresolved = []

    for link in links:
        target = link["target"]
        target_id = resolved.get(target)
        if target_id and target_id != doc_id:
            try:
                await pg.add_trace(
                    source_id=doc_id,
                    target_id=target_id,
                    relation="references",
                    confidence=0.9,
                )
                traces_created += 1
            except Exception as e:
                log.warning("Failed to create trace %s -> %s: %s", doc_id, target_id, e)
        else:
            unresolved.append(target)

    return {
        "links_found": len(links),
        "traces_created": traces_created,
        "unresolved": unresolved,
    }
