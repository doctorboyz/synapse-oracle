"""Topic monitor — periodically search configured topics and ingest results.

Background task that reads search_topics table, searches web/social,
and pushes new results to synapse vault.
"""

import logging

from src.db.pg_store import PgStore
from src.ingest.push import Push
from src.connectors.web_search import WebSearchConnector
from src.connectors.social_search import SocialSearchConnector

log = logging.getLogger("synapse.connectors.topic_monitor")

# Deduplicate by URL hash within a search session
_seen_urls: set[str] = set()


async def run_topic_monitor(
    pg: PgStore,
    push: Push,
    web_search: WebSearchConnector | None = None,
    social_search: SocialSearchConnector | None = None,
    limit_per_topic: int = 5,
) -> dict:
    """Run one pass of topic monitoring.

    Returns: {topics_checked, results_found, indexed, duplicates, errors}
    """
    global _seen_urls
    _seen_urls = set()

    web = web_search or WebSearchConnector()
    social = social_search or SocialSearchConnector()

    # Get all enabled topics
    topics = await pg.list_search_topics(enabled_only=True)
    log.info("Topic monitor: %d enabled topics to check", len(topics))

    stats = {
        "topics_checked": 0,
        "results_found": 0,
        "indexed": 0,
        "duplicates": 0,
        "errors": 0,
    }

    for topic_row in topics:
        topic_id = topic_row["id"]
        scope = topic_row["scope"]
        topic = topic_row["topic"]
        source = topic_row["source"]
        tags = [scope] if scope else []

        stats["topics_checked"] += 1
        log.info("Checking topic: %s (source=%s, tags=%s)", topic, source, tags)

        try:
            results = []
            if source == "web":
                results = await web.search(topic, limit=limit_per_topic)
            elif source in ("twitter", "reddit", "hackernews"):
                results = await social.search(source, topic, limit=limit_per_topic)
            else:
                log.warning("Unknown source: %s", source)
                continue

            stats["results_found"] += len(results)

            for result in results:
                url = getattr(result, "url", "")
                if not url or url in _seen_urls:
                    continue
                _seen_urls.add(url)

                # Check if URL already indexed in this scope
                existing = await pg.find_by_source_file(url, scope)
                if existing:
                    stats["duplicates"] += 1
                    continue

                # Fetch full content for web results
                content = getattr(result, "snippet", "")
                if source == "web" and url:
                    fetched = await web.fetch_page(url)
                    if fetched:
                        content = fetched

                title = getattr(result, "title", "") or topic
                if len(content) < 50:
                    log.debug("Skipping short content: %s", url)
                    continue

                result_push = await push.push_text(
                    title=title[:200],
                    content=content,
                    tags=tags,
                    doc_type="note",
                    source_type=source,
                    source_file=url,
                    source_project=scope,
                )
                if result_push.get("status") == "duplicate":
                    stats["duplicates"] += 1
                elif result_push.get("status") == "indexed":
                    stats["indexed"] += 1

            # Update last_searched
            await pg.update_search_topic_last_searched(topic_id)

        except Exception as e:
            log.error("Topic monitor failed for %s: %s", topic, e)
            stats["errors"] += 1

    return stats
