"""Reconcile — defrag duplicates + detox conflicts."""

from src.reconcile.defrag import defrag
from src.reconcile.detox import detox


async def reconcile(
    pg,
    embedder=None,
    settings=None,
    scope: str | None = None,
    tags: list[str] | None = None,
    cross_scope: bool = False,
    dry_run: bool = False,
) -> dict:
    """Run full reconcile: defrag + detox.

    When cross_scope=True, both defrag and detox search across all tags
    using pgvector ANN (embedding similarity) to find duplicates/conflicts.
    """
    defrag_result = await defrag(
        pg=pg,
        embedder=embedder,
        scope=scope,
        tags=tags,
        cross_scope=cross_scope,
        similarity_threshold=0.95,
        dry_run=dry_run,
    )
    detox_result = await detox(
        pg=pg,
        embedder=embedder,
        settings=settings,
        scope=scope,
        tags=tags,
        cross_scope=cross_scope,
        similarity_threshold=0.70,
        dry_run=dry_run,
    )

    return {
        "defrag": defrag_result,
        "detox": detox_result,
        "scope": scope or "all",
        "tags": tags,
        "cross_scope": cross_scope,
        "dry_run": dry_run,
    }
