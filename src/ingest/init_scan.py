"""Init scan — walk directory, extract metadata, optionally summarize with LLM, push to vault."""

import hashlib
import logging
import os
from pathlib import Path

from src.config import Settings
from src.db.pg_store import PgStore
from src.embed.ollama import OllamaEmbedder
from src.ingest.oracle_paths import extract_metadata
from src.ingest.push import Push
from src.ingest.concepts import extract_concepts

log = logging.getLogger("synapse.init")

SCAN_EXTENSIONS = {".md", ".txt", ".rst", ".pdf", ".docx"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache", ".pytest_cache"}


def should_skip(path: Path) -> bool:
    """Return True if path should be skipped during scan."""
    parts = path.parts
    for part in parts:
        if part in SKIP_DIRS or part.startswith("."):
            return True
    return False


def scan_files(root: Path) -> list[Path]:
    """Walk directory tree, return matching files."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not should_skip(Path(dirpath) / d)]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() in SCAN_EXTENSIONS and not should_skip(fpath):
                files.append(fpath)
    return sorted(files)


def read_text_file(path: Path) -> str | None:
    """Read a text file, return content or None on error."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        log.warning("Failed to read %s: %s", path, e)
        return None


def read_pdf_file(path: Path) -> str | None:
    """Read a PDF file, return text content or None."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages) if pages else None
    except ImportError:
        log.error("pypdf not installed. Install with: pip install synapse[init]")
        return None
    except Exception as e:
        log.warning("Failed to read PDF %s: %s", path, e)
        return None


def read_docx_file(path: Path) -> str | None:
    """Read a DOCX file, return text content or None."""
    try:
        from docx import Document
        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs) if paragraphs else None
    except ImportError:
        log.error("python-docx not installed. Install with: pip install synapse[init]")
        return None
    except Exception as e:
        log.warning("Failed to read DOCX %s: %s", path, e)
        return None


def read_file_content(path: Path) -> str | None:
    """Read file content based on extension."""
    ext = path.suffix.lower()
    if ext in {".md", ".txt", ".rst"}:
        return read_text_file(path)
    elif ext == ".pdf":
        return read_pdf_file(path)
    elif ext == ".docx":
        return read_docx_file(path)
    return None


async def summarize_with_llm(content: str, title: str, embedder: OllamaEmbedder) -> str | None:
    """Use LLM to summarize content. Returns summary or None if LLM unavailable."""
    try:
        import httpx
        settings = embedder.settings
        prompt = (
            f"Summarize the following document concisely, preserving key information. "
            f"Keep the summary under 500 words.\n\n"
            f"Title: {title}\n\n"
            f"Content:\n{content[:8000]}"
        )
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": "kimi-k2.6:cloud",
                    "prompt": prompt,
                    "stream": False,
                },
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("response", "").strip()
    except Exception as e:
        log.warning("LLM summarization failed: %s: %s", type(e).__name__, e)
    return None


async def init_scan(
    path: str,
    tags: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Scan directory, extract metadata, optionally summarize with LLM, push to vault.

    Returns dict with: total_files, indexed, duplicates, errors, files (list of details)
    """
    root = Path(path).resolve()
    if not root.exists():
        return {"error": f"Path not found: {root}"}
    if not root.is_dir():
        return {"error": f"Not a directory: {root}"}

    files = scan_files(root)
    log.info("Found %d files to scan in %s", len(files), root)

    settings = Settings()
    pg = PgStore(settings)
    await pg.connect()

    embedder = None
    try:
        embedder = OllamaEmbedder(settings)
    except Exception:
        log.warning("Ollama not available, no LLM summarization")

    push = Push(pg, embedder)

    results = {
        "total_files": len(files),
        "indexed": 0,
        "duplicates": 0,
        "errors": 0,
        "superseded": 0,
        "skipped_unchanged": 0,
        "files": [],
    }

    for fpath in files:
        rel_path = str(fpath.relative_to(root))
        file_info = {"path": rel_path, "status": "pending"}
        log.info("Processing: %s", rel_path)

        content = read_file_content(fpath)
        if content is None:
            results["errors"] += 1
            file_info["status"] = "error"
            file_info["error"] = "Failed to read file"
            results["files"].append(file_info)
            continue

        if not content.strip():
            file_info["status"] = "skipped"
            file_info["error"] = "Empty content"
            results["files"].append(file_info)
            continue

        # Extract metadata from oracle path
        metadata = extract_metadata(str(fpath), str(root))
        file_tags = tags or metadata.get("tags", [])
        doc_type = metadata.get("doc_type", "note")
        oracle_name = metadata.get("oracle_name")
        brain_path = metadata.get("brain_path")
        brain_tier = metadata.get("brain_tier")

        title = fpath.stem.replace("-", " ").replace("_", " ").title()
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        source_project = oracle_name or (file_tags[0] if file_tags else None)

        # Check if file already indexed — skip if unchanged, supersede if updated
        existing = await pg.find_by_source_file(rel_path, source_project or "", include_hash=True)
        if existing:
            if existing.get("content_hash") == content_hash:
                results["skipped_unchanged"] += 1
                file_info["status"] = "skipped_unchanged"
                file_info["id"] = existing["id"]
                results["files"].append(file_info)
                continue
            else:
                log.info("File updated, superseding: %s (old=%s)", rel_path, existing["id"])

        if dry_run:
            file_info["status"] = "dry_run"
            file_info["tags"] = file_tags
            file_info["doc_type"] = doc_type
            file_info["title"] = title
            file_info["content_length"] = len(content)
            results["files"].append(file_info)
            continue

        try:
            concepts = extract_concepts(content)
            if existing:
                result = await push.supersede_and_reindex(
                    old_id=existing["id"],
                    content=content,
                    title=title,
                    doc_type=doc_type,
                    source_file=rel_path,
                    source_project=source_project,
                    oracle_name=oracle_name,
                    brain_path=brain_path,
                    brain_tier=brain_tier,
                    concepts=concepts,
                    tags=file_tags,
                )
                status = result.get("status", "unknown")
                file_info["status"] = status
                file_info["id"] = result.get("id")
                file_info["tags"] = result.get("tags")
                results["superseded"] += 1
            else:
                result = await push.push_text(
                    title=title,
                    content=content,
                    doc_type=doc_type,
                    source_file=rel_path,
                    source_type="init_scan",
                    source_project=source_project,
                    oracle_name=oracle_name,
                    brain_path=brain_path,
                    brain_tier=brain_tier,
                    trace_content=content,
                    concepts=concepts,
                    tags=file_tags,
                    skip_semantic_dedup=True,
                )
                status = result.get("status", "unknown")
                file_info["status"] = status
                file_info["id"] = result.get("id")
                file_info["tags"] = result.get("tags")

                if status == "duplicate":
                    results["duplicates"] += 1
                else:
                    results["indexed"] += 1
        except Exception as e:
            log.error("Failed to push %s: %s", rel_path, e)
            results["errors"] += 1
            file_info["status"] = "error"
            file_info["error"] = str(e)

        results["files"].append(file_info)

    # Cleanup
    await pg.close()

    return results