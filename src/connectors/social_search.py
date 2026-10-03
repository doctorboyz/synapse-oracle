"""Social search connector — search social platforms for topics.

Supports: twitter (X), reddit, hackernews.
"""

import logging

import httpx

from src.config import Settings

log = logging.getLogger("synapse.connectors.social_search")


class SocialSearchResult:
    """Single social search result."""

    def __init__(self, title: str, url: str, snippet: str, author: str = "",
                 platform: str = "", posted_at: str = ""):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.author = author
        self.platform = platform
        self.posted_at = posted_at

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "author": self.author,
            "platform": self.platform,
            "posted_at": self.posted_at,
        }


class SocialSearchConnector:
    """Search social platforms for topics."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    async def search(self, platform: str, query: str, limit: int = 10) -> list[SocialSearchResult]:
        """Search a social platform for a query."""
        if platform == "twitter":
            return await self._search_twitter(query, limit)
        if platform == "reddit":
            return await self._search_reddit(query, limit)
        if platform == "hackernews":
            return await self._search_hackernews(query, limit)
        log.warning("Unknown social platform: %s", platform)
        return []

    async def _search_twitter(self, query: str, limit: int) -> list[SocialSearchResult]:
        """Search Twitter/X via Nitter (no API key needed) or fallback to scraping."""
        try:
            # Use Nitter instance for search (no auth needed)
            nitter_url = f"https://nitter.net/search?f=tweets&q={query.replace(' ', '+')}"
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(nitter_url)
                if resp.status_code != 200:
                    return []

                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                tweets = soup.find_all("div", class_="timeline-item")

                results = []
                for tweet in tweets[:limit]:
                    text_elem = tweet.find("div", class_="tweet-content")
                    text = text_elem.get_text(strip=True) if text_elem else ""
                    link_elem = tweet.find("a", class_="tweet-date")
                    link = "https://twitter.com" + link_elem["href"] if link_elem and link_elem.get("href") else ""
                    author_elem = tweet.find("a", class_="username")
                    author = author_elem.get_text(strip=True) if author_elem else ""

                    if text:
                        results.append(
                            SocialSearchResult(
                                title=text[:100],
                                url=link,
                                snippet=text,
                                author=author,
                                platform="twitter",
                            )
                        )
                return results
        except Exception as e:
            log.warning("Twitter search failed: %s", e)
            return []

    async def _search_reddit(self, query: str, limit: int) -> list[SocialSearchResult]:
        """Search Reddit via Reddit JSON API (no auth needed for read)."""
        try:
            url = f"https://www.reddit.com/search.json?q={query.replace(' ', '+')}&limit={min(limit, 25)}"
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "synapse-search/1.0"})
                resp.raise_for_status()
                data = resp.json()

                results = []
                for post in data.get("data", {}).get("children", []):
                    p = post.get("data", {})
                    title = p.get("title", "")
                    url = "https://reddit.com" + p.get("permalink", "")
                    snippet = p.get("selftext", "") or title
                    author = p.get("author", "")
                    created = p.get("created_utc", "")

                    results.append(
                        SocialSearchResult(
                            title=title,
                            url=url,
                            snippet=snippet[:500],
                            author=author,
                            platform="reddit",
                            posted_at=str(created),
                        )
                    )
                return results
        except Exception as e:
            log.warning("Reddit search failed: %s", e)
            return []

    async def _search_hackernews(self, query: str, limit: int) -> list[SocialSearchResult]:
        """Search Hacker News via Algolia API (no auth needed)."""
        try:
            url = f"https://hn.algolia.com/api/v1/search?query={query.replace(' ', '+')}&hitsPerPage={min(limit, 20)}"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

                results = []
                for hit in data.get("hits", []):
                    title = hit.get("title", "") or hit.get("story_title", "")
                    url = hit.get("url", "") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
                    snippet = hit.get("comment_text", "") or title
                    author = hit.get("author", "")
                    created = hit.get("created_at", "")

                    if title:
                        results.append(
                            SocialSearchResult(
                                title=title,
                                url=url,
                                snippet=snippet[:500],
                                author=author,
                                platform="hackernews",
                                posted_at=created,
                            )
                        )
                return results
        except Exception as e:
            log.warning("HackerNews search failed: %s", e)
            return []
