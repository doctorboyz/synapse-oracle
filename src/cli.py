"""CLI helpers — shared async setup/teardown and output formatting."""

import asyncio
import json
import logging
import sys
from functools import wraps

from src.config import Settings
from src.db.pg_store import PgStore
from src.embed.ollama import OllamaEmbedder
from src.ingest.push import Push
from src.retrieve.hybrid_search import HybridSearch

log = logging.getLogger("synapse.cli")


class Components:
    """Holds all initialized service connections."""

    def __init__(
        self,
        settings: Settings,
        pg: PgStore,
        embedder: OllamaEmbedder | None,
        push: Push,
        search: HybridSearch,
    ):
        self.settings = settings
        self.pg = pg
        self.embedder = embedder
        self.push = push
        self.search = search


async def get_components() -> Components:
    """Create settings, connect PG/Ollama, return Components."""
    settings = Settings()

    pg = PgStore(settings)
    await pg.connect()

    embedder = None
    try:
        embedder = OllamaEmbedder(settings)
    except Exception:
        log.warning("Ollama not available, running without embeddings")
        embedder = None

    push = Push(pg, embedder)
    search = HybridSearch(pg, embedder, settings.search_weights, settings.search_rrf_k)

    return Components(settings, pg, embedder, push, search)


async def cleanup(components: Components) -> None:
    """Close all connections."""
    if components.pg:
        await components.pg.close()


def format_json(data) -> str:
    """Format data as JSON string."""
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)


def output(data) -> None:
    """Print JSON to stdout."""
    print(format_json(data))


def cli_command(func):
    """Decorator for async CLI commands: handles setup/teardown and errors."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        async def run():
            components = await get_components()
            try:
                result = await func(components, *args, **kwargs)
                output(result)
            except Exception as e:
                output({"error": str(e), "command": func.__name__})
                sys.exit(1)
            finally:
                await cleanup(components)

        asyncio.run(run())

    return wrapper