"""Async Ollama embedder with retry, batch, and timeout."""

import asyncio
import logging

import httpx

from src.config import Settings

log = logging.getLogger("synapse.embed")

MAX_CHUNK_CHARS = 4000


class OllamaEmbedder:
    """Async Ollama embedding client with retry logic and real batching.

    - Reuses one httpx.AsyncClient across calls (no per-call TCP+TLS setup)
    - embed_batch sends all texts in a single /api/embed request
      (Ollama accepts `input` as an array) instead of a serial loop
    """

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or Settings()
        self.settings = self._settings
        self._base_url = self._settings.ollama_url
        self._model = self._settings.embedding_model
        self._dim = self._settings.embedding_dim
        self._timeout = self._settings.embedding_timeout
        self._max_retries = 2
        self._batch_semaphore = asyncio.Semaphore(4)
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        """Close the shared HTTP client (graceful shutdown paths)."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def embed(self, text: str) -> list[float]:
        text = text[:MAX_CHUNK_CHARS]
        for attempt in range(self._max_retries + 1):
            try:
                client = self._get_client()
                resp = await client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": text},
                )
                resp.raise_for_status()
                data = resp.json()
                return data["embeddings"][0]
            except (httpx.HTTPError, KeyError, IndexError) as e:
                if attempt == self._max_retries:
                    raise EmbeddingError(f"Embedding failed after {attempt+1} attempts: {e}") from e
                wait = 0.5 * (2 ** attempt)
                log.warning("Embed retry %d/%d: %s", attempt + 1, self._max_retries, e)
                await asyncio.sleep(wait)
        raise EmbeddingError("Unreachable")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts in ONE /api/embed call (input array).

        Falls back to per-text embed if the server rejects array input.
        """
        if not texts:
            return []
        async with self._batch_semaphore:
            truncated = [t[:MAX_CHUNK_CHARS] for t in texts]
            for attempt in range(self._max_retries + 1):
                try:
                    client = self._get_client()
                    resp = await client.post(
                        f"{self._base_url}/api/embed",
                        json={"model": self._model, "input": truncated},
                    )
                    resp.raise_for_status()
                    embeddings = resp.json()["embeddings"]
                    if len(embeddings) != len(truncated):
                        raise EmbeddingError(
                            f"Batch mismatch: sent {len(truncated)}, "
                            f"got {len(embeddings)}"
                        )
                    return embeddings
                except (httpx.HTTPError, KeyError, IndexError, EmbeddingError) as e:
                    if attempt == self._max_retries:
                        log.warning(
                            "Batch embed failed (%s), falling back to serial: %s",
                            type(e).__name__, e,
                        )
                        return [await self.embed(t) for t in texts]
                    wait = 0.5 * (2 ** attempt)
                    log.warning("Batch embed retry %d/%d: %s",
                                attempt + 1, self._max_retries, e)
                    await asyncio.sleep(wait)
        raise EmbeddingError("Unreachable")

    async def check(self) -> bool:
        try:
            await self.embed("health check")
            return True
        except Exception:
            return False


class EmbeddingError(Exception):
    pass