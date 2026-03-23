"""Shared 4-step recommendation pipeline for users and groups.

Step 1: Main algorithm scoring (pgvector + reranking)
Step 2: Main probabilistic sampling (500 → 200, tier shuffle)
Step 3: Exploration scoring (novelty + consensus + trending)
Step 4: Exploration sampling + blending with main results
"""

import random
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session, defer

from app.import_data.models import MovieEmbedding
from app.movies.models import Movie
from app.recommendations.ranking import (
    EXPLORE_TEMPERATURE,
    probabilistic_sample,
    rerank_candidates,
    score_exploration,
    to_match_percentage,
)

CANDIDATE_POOL_SIZE = 500
EXPLORE_POOL_SIZE = 500
ALGO_RATIO = 0.92  # 92% algo, 8% exploration


@dataclass
class RecommendationContext:
    positive_embedding: list[float]
    negative_embedding: list[float] | None = None
    exclude_ids: list[int] = field(default_factory=list)
    user_genres: list[str] = field(default_factory=list)
    top_directors: set[str] = field(default_factory=set)
    top_cast: set[str] = field(default_factory=set)
    genre_watch_counts: dict[str, int] = field(default_factory=dict)
    total_watches: int = 0


def run_recommendation_pipeline(
    ctx: RecommendationContext,
    db: Session,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Execute the 4-step recommendation pipeline.

    Returns list of dicts with movie data + score, ready for response serialization.
    """
    # Step 1 + 2: Main algorithm
    main_sampled = _run_main_algorithm(ctx, db)

    # Step 3 + 4: Exploration
    main_tmdb_ids = {c["tmdb_id"] for c in main_sampled}
    explore_sampled = _run_exploration(ctx, db, main_tmdb_ids)

    # Blend: 85% algo, 15% exploration
    algo_count = round(limit * ALGO_RATIO)
    explore_count = limit - algo_count

    # Handle edge cases: not enough from one pool
    main_page = main_sampled[offset : offset + algo_count]
    if len(main_page) < algo_count and explore_sampled:
        # Fill remaining with exploration
        explore_count += algo_count - len(main_page)
    elif not explore_sampled:
        # No exploration candidates: all algo
        main_page = main_sampled[offset : offset + limit]
        explore_count = 0

    explore_page = explore_sampled[:explore_count] if explore_count > 0 else []

    # Rescale exploration scores to blend naturally with main scores
    if main_page and explore_page:
        explore_page = _rescale_exploration_scores(main_page, explore_page)

    # Merge and shuffle
    combined = main_page + explore_page
    random.shuffle(combined)

    # Format results
    return [_format_candidate(c) for c in combined]


def _run_main_algorithm(ctx: RecommendationContext, db: Session) -> list[dict]:
    """Steps 1-2: pgvector candidates → rerank → probabilistic sample."""
    embedding_str = "[" + ",".join(str(v) for v in ctx.positive_embedding) + "]"

    result = db.execute(
        text(
            "SELECT * FROM match_movies("
            "cast(:query_embedding AS vector(1536)), :match_count, :exclude_ids"
            ")"
        ),
        {
            "query_embedding": embedding_str,
            "match_count": CANDIDATE_POOL_SIZE,
            "exclude_ids": ctx.exclude_ids if ctx.exclude_ids else [],
        },
    )
    rows = result.fetchall()
    if not rows:
        return []

    tmdb_ids = [row[0] for row in rows]
    similarity_map = {row[0]: row[1] for row in rows}

    movies = db.query(Movie).filter(Movie.tmdb_id.in_(tmdb_ids)).all()
    movie_map = {m.tmdb_id: m for m in movies}

    # Fetch candidate embeddings for negative penalty
    candidate_embeddings: dict[int, list[float]] | None = None
    if ctx.negative_embedding:
        emb_rows = (
            db.query(MovieEmbedding).filter(MovieEmbedding.tmdb_id.in_(tmdb_ids)).all()
        )
        candidate_embeddings = {e.tmdb_id: list(e.embedding) for e in emb_rows}

    candidates = []
    for tmdb_id in tmdb_ids:
        movie = movie_map.get(tmdb_id)
        if not movie:
            continue
        # Filter out short films and movies with no community validation
        if (movie.runtime or 0) < 45 or (movie.vote_average or 0) < 1.0:
            continue
        candidates.append(
            {
                "tmdb_id": tmdb_id,
                "similarity": similarity_map[tmdb_id],
                "movie": movie,
            }
        )

    # Rerank with negative penalty
    ranked = rerank_candidates(
        candidates,
        ctx.user_genres,
        ctx.top_directors,
        ctx.top_cast,
        negative_embedding=ctx.negative_embedding,
        candidate_embeddings=candidate_embeddings,
    )

    # Probabilistic sample 500 → 200
    return probabilistic_sample(ranked)


def _run_exploration(
    ctx: RecommendationContext,
    db: Session,
    exclude_tmdb_ids: set[int],
) -> list[dict]:
    """Steps 3-4: Fetch exploration pool, score, sample."""
    # Combine all exclusion IDs
    all_exclude = set(ctx.exclude_ids) | exclude_tmdb_ids

    # Query high vote_average movies from DB, excluding watched/hidden/algo picks
    # Defer cast JSONB — not needed for exploration scoring or formatting
    query = (
        db.query(Movie)
        .options(defer(Movie.cast))
        .filter(
            Movie.vote_average.isnot(None),
            Movie.vote_average >= 6.0,
            Movie.vote_count >= 50,
            Movie.runtime >= 45,
        )
    )
    if all_exclude:
        query = query.filter(Movie.tmdb_id.notin_(list(all_exclude)))

    query = query.order_by(Movie.vote_average.desc()).limit(EXPLORE_POOL_SIZE)
    explore_movies = query.all()

    if not explore_movies:
        return []

    # Compute genre frequency for novelty scoring
    total = ctx.total_watches if ctx.total_watches > 0 else 0
    genre_freq: dict[str, float] = {}
    if total > 0:
        genre_freq = {g: c / total for g, c in ctx.genre_watch_counts.items()}

    # Score each candidate
    explore_candidates = []
    for movie in explore_movies:
        explore_score = score_exploration(movie, genre_freq, total)
        explore_candidates.append(
            {
                "tmdb_id": movie.tmdb_id,
                "similarity": 0.0,
                "movie": movie,
                "score": explore_score,
            }
        )

    # Sort and sample with higher temperature
    explore_candidates.sort(key=lambda c: c["score"], reverse=True)
    return probabilistic_sample(
        explore_candidates, sample_size=50, temperature=EXPLORE_TEMPERATURE
    )


def _rescale_exploration_scores(
    main_page: list[dict], explore_page: list[dict]
) -> list[dict]:
    """Rescale exploration scores to P25-P75 of main scores."""
    main_scores = [c["score"] for c in main_page]
    if not main_scores:
        return explore_page

    p25 = float(np.percentile(main_scores, 25))
    p75 = float(np.percentile(main_scores, 75))

    exp_scores = [c["score"] for c in explore_page]
    exp_min = min(exp_scores)
    exp_max = max(exp_scores)

    for c in explore_page:
        if exp_max == exp_min:
            c["score"] = round((p25 + p75) / 2, 4)
        else:
            c["score"] = round(
                p25 + (c["score"] - exp_min) * (p75 - p25) / (exp_max - exp_min), 4
            )

    return explore_page


def _format_candidate(c: dict) -> dict:
    """Format a candidate dict for response serialization."""
    movie = c["movie"]
    return {
        "tmdb_id": movie.tmdb_id,
        "title": movie.title,
        "year": movie.year,
        "overview": movie.overview,
        "poster_path": movie.poster_path,
        "genres": movie.genres or [],
        "director": movie.director,
        "similarity": round(c.get("similarity", 0.0), 4),
        "score": to_match_percentage(c["score"]),
    }
