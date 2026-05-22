"""OpenRouter client — cheap, reliable LLM with Ollama fallback."""

import base64
import json
import logging
from typing import Any

import httpx

from src.config import Settings

log = logging.getLogger("synapse.openrouter")


class OpenRouterError(Exception):
    """Base error for OpenRouter client."""


class OpenRouterClient:
    """Async OpenRouter API client with Ollama fallback."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self._api_key = self.settings.openrouter_api_key
        self._base_url = self.settings.openrouter_base_url.rstrip("/")
        self._default_timeout = self.settings.openrouter_timeout

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> str:
        """Send chat completion request. Returns assistant content or raises."""
        if not self.enabled:
            raise OpenRouterError("OpenRouter API key not configured")

        model = model or self.settings.openrouter_model
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://synapse.doctorboyz.com",
            "X-Title": "Synapse Knowledge Base",
        }

        async with httpx.AsyncClient(timeout=timeout or self._default_timeout) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content.strip()

    async def summarize(
        self,
        text: str,
        model: str | None = None,
        language: str = "auto",
    ) -> str:
        """Summarize text. Falls back to Ollama if OpenRouter unavailable."""
        system = (
            "You are a concise knowledge summarizer. Summarize as 2-3 short bullet points "
            "preserving key facts. Use bullet format (each line starts with -). "
            "Respond ONLY with the bullet summary."
        )
        if language != "auto":
            system += f" Use {language}."
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Summarize:\n\n{text[:8000]}"},
        ]
        try:
            return await self.chat(
                messages,
                model=model or self.settings.openrouter_summary_model,
                temperature=0.3,
            )
        except Exception as e:
            log.warning("OpenRouter summarize failed: %s", e)
            return await _ollama_summarize(text, self.settings)

    async def ocr_image(
        self,
        image_bytes: bytes,
        model: str | None = None,
    ) -> str | None:
        """OCR an image using vision model. Returns text or None if no text found."""
        if not self.enabled:
            return await _ollama_ocr(image_bytes, self.settings)

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        ext = _guess_image_ext(image_bytes)
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Extract all readable text from this image. "
                            "If no text is found, respond with exactly 'NO_TEXT_FOUND'."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/{ext};base64,{b64}",
                        },
                    },
                ],
            },
        ]
        try:
            text = await self.chat(
                messages,
                model=model or self.settings.openrouter_vision_model,
                temperature=0.1,
                timeout=60,
            )
            if "NO_TEXT_FOUND" in text.upper() or not text:
                return None
            return text
        except Exception as e:
            log.warning("OpenRouter OCR failed: %s", e)
            return await _ollama_ocr(image_bytes, self.settings)


# --- Ollama fallback helpers ---

async def _ollama_summarize(text: str, settings: Settings) -> str:
    """Fallback summarization via Ollama."""
    import httpx

    payload = {
        "model": "qwen2.5:7b",
        "messages": [
            {"role": "system", "content": "You are a helpful summarizer."},
            {"role": "user", "content": f"Summarize this:\n\n{text[:4000]}"},
        ],
        "stream": False,
        "options": {"temperature": 0.3},
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.ollama_url}/api/chat", json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "").strip() or text[:200]
    except Exception as e:
        log.warning("Ollama fallback summarize failed: %s", e)
        return text[:200]


async def _ollama_ocr(image_bytes: bytes, settings: Settings) -> str | None:
    """Fallback OCR via Ollama vision model."""
    import httpx

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "model": "qwen2.5:7b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all text from this image."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            },
        ],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.ollama_url}/api/chat", json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("message", {}).get("content", "").strip()
            if "NO_TEXT_FOUND" in text.upper() or not text:
                return None
            return text
    except Exception as e:
        log.warning("Ollama fallback OCR failed: %s", e)
        return None


def _guess_image_ext(image_bytes: bytes) -> str:
    """Guess image extension from magic bytes."""
    if image_bytes[:2] == b"\xff\xd8":
        return "jpeg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if image_bytes[:4] == b"GIF8":
        return "gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "webp"
    return "jpeg"
