"""Web search connector — search web for topics and return results.

Supports multiple providers: serper, tavily, duckduckgo.
"""

import logging

import httpx

from src.config import Settings

log = logging.getLogger("synapse.connectors.web_search")


class WebSearchResult:
    """Single search result."""

    def __init__(self, title: str, url: str, snippet: str, source: str = "web"):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source = source

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
        }


class WebSearchConnector:
    """Search the web for topics using configured provider."""

    VALID_PROVIDERS = {"serper", "tavily", "duckduckgo"}

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.provider = self._detect_provider()
        self.api_key = self._get_api_key()

    def _detect_provider(self) -> str:
        provider = (
            getattr(self.settings, "web_search_provider", None)
            or "serper"
        )
        if provider not in self.VALID_PROVIDERS:
            log.warning("Unknown provider '%s', falling back to serper", provider)
            return "serper"
        return provider

    def _get_api_key(self) -> str | None:
        if self.provider == "serper":
            return getattr(self.settings, "serper_api_key", None) or ""
        if self.provider == "tavily":
            return getattr(self.settings, "tavily_api_key", None) or ""
        return None

    async def search(self, query: str, limit: int = 10) -> list[WebSearchResult]:
        """Search the web for a query. Returns list of results."""
        if self.provider == "serper":
            return await self._search_serper(query, limit)
        if self.provider == "tavily":
            return await self._search_tavily(query, limit)
        if self.provider == "duckduckgo":
            return await self._search_duckduckgo(query, limit)
        return []

    async def _search_serper(self, query: str, limit: int) -> list[WebSearchResult]:
        """Search via Serper.dev (Google Search API)."""
        if not self.api_key:
            log.warning("SERPER_API_KEY not set, skipping web search")
            return []

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": min(limit, 20)},
                )
                resp.raise_for_status()
                data = resp.json()

                results = []
                for item in data.get("organic", []):
                    results.append(
                        WebSearchResult(
                            title=item.get("title", ""),
                            url=item.get("link", ""),
                            snippet=item.get("snippet", ""),
                            source="web",
                        )
                    )
                return results
        except Exception as e:
            log.warning("Serper search failed: %s", e)
            return []

    async def _search_tavily(self, query: str, limit: int) -> list[WebSearchResult]:
        """Search via Tavily AI Search API."""
        if not self.api_key:
            log.warning("TAVILY_API_KEY not set, skipping web search")
            return []

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    headers={"Content-Type": "application/json"},
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "max_results": min(limit, 20),
                        "search_depth": "basic",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                results = []
                for item in data.get("results", []):
                    results.append(
                        WebSearchResult(
                            title=item.get("title", ""),
                            url=item.get("url", ""),
                            snippet=item.get("content", ""),
                            source="web",
                        )
                    )
                return results
        except Exception as e:
            log.warning("Tavily search failed: %s", e)
            return []

    async def _search_duckduckgo(self, query: str, limit: int) -> list[WebSearchResult]:
        """Search via DuckDuckGo HTML scraping (no API key needed)."""
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = []
                for item in ddgs.text(query, max_results=min(limit, 20)):
                    results.append(
                        WebSearchResult(
                            title=item.get("title", ""),
                            url=item.get("href", ""),
                            snippet=item.get("body", ""),
                            source="web",
                        )
                    )
                return results
        except ImportError:
            log.warning("duckduckgo-search not installed. pip install duckduckgo-search")
            return []
        except Exception as e:
            log.warning("DuckDuckGo search failed: %s", e)
            return []

    async def fetch_page(self, url: str) -> str:
        """Fetch and extract text content from a URL."""
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                # Remove script/style
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
                # Truncate if too long
                if len(text) > 50000:
                    text = text[:50000] + "\n\n[...truncated]"
                return text
        except Exception as e:
            log.warning("Failed to fetch %s: %s", url, e)
            return ""
