"""Async Ollama embedder with retry, batch, and timeout."""

import asyncio
import logging

import httpx

from src.config import Settings

log = logging.getLogger("synapse.embed")

MAX_CHUNK_CHARS = 4000


class OllamaEmbedder:
    """Async Ollama embedding client with retry logic and batching."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or Settings()
        self.settings = self._settings
        self._base_url = self._settings.ollama_url
        self._model = self._settings.embedding_model
        self._dim = self._settings.embedding_dim
        self._timeout = self._settings.embedding_timeout
        self._max_retries = 2
        self._batch_semaphore = asyncio.Semaphore(4)

    async def embed(self, text: str) -> list[float]:
        text = text[:MAX_CHUNK_CHARS]
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
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
        async with self._batch_semaphore:
            results = []
            for text in texts:
                vec = await self.embed(text)
                results.append(vec)
            return results

    async def check(self) -> bool:
        try:
            await self.embed("health check")
            return True
        except Exception:
            return False


class EmbeddingError(Exception):
    pass