"""Shared over-fetch + softmax sampling for TMDB browse endpoints.

Fetches multiple pages concurrently, deduplicates, and softmax-samples
so each request returns a different subset of quality movies.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable

import numpy as np

OVERFETCH_PAGES = 5
SAMPLE_SIZE = 20
TEMPERATURE = 1.2


def softmax_sample(
    items: list[dict],
    sample_size: int = SAMPLE_SIZE,
    temperature: float = TEMPERATURE,
) -> list[dict]:
    """Softmax-weighted sampling using vote_average as the score signal."""
    if len(items) <= sample_size:
        sampled = list(items)
        random.shuffle(sampled)
        return sampled

    scores = np.array([item.get("vote_average") or 5.0 for item in items])
    exp_scores = np.exp(scores / temperature)
    probabilities = exp_scores / exp_scores.sum()

    indices = np.random.choice(
        len(items), size=sample_size, replace=False, p=probabilities
    )
    sampled = [items[i] for i in indices]
    random.shuffle(sampled)
    return sampled


async def fetch_and_sample(
    fetch_page: Callable[[int], Awaitable[list[dict]]],
    sample_size: int = SAMPLE_SIZE,
    pages: int = OVERFETCH_PAGES,
    exclude: set[int] | None = None,
) -> dict:
    """Over-fetch multiple TMDB pages concurrently, deduplicate, softmax-sample.

    Args:
        fetch_page: async callable that takes a page number and returns a list of movie dicts.
        sample_size: how many movies to return.
        pages: how many TMDB pages to fetch.
        exclude: tmdb_ids to filter out (already seen by frontend).

    Returns:
        {"results": [...], "total_results": int}
    """
    tasks = [fetch_page(p) for p in range(1, pages + 1)]
    page_results = await asyncio.gather(*tasks)

    exclude_ids = exclude or set()

    # Flatten, deduplicate, and exclude already-seen
    seen: set[int] = set()
    pool: list[dict] = []
    for page in page_results:
        for item in page:
            tid = item["tmdb_id"]
            if tid not in seen and tid not in exclude_ids:
                seen.add(tid)
                pool.append(item)

    results = softmax_sample(pool, sample_size)
    return {"results": results, "total_results": len(pool)}
