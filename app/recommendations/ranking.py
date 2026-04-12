"""Re-ranking layer for recommendation candidates.

Architecture: pgvector returns ~500 candidates by cosine similarity,
then this module re-ranks using structured signals (genre, consensus, director, cast).
Negative embedding penalty pushes down movies similar to disliked content.
Probabilistic softmax sampling selects 200 from the pool (favoring higher scores),
then candidates within the same score tier are shuffled for additional variety.
"""

import random
from datetime import datetime, timezone

import numpy as np

from app.movies.models import Movie

# Weights — easy to tune later
W_SIMILARITY = 0.50
W_GENRE = 0.20
W_CONSENSUS = 0.20
W_DIRECTOR = 0.05
W_CAST = 0.05
W_NEGATIVE = 0.15

# Exploration weights
W_NOVELTY = 0.50
W_CONSENSUS_EXPLORE = 0.40
W_TRENDING = 0.10


def _genre_overlap(movie_genres: list[dict], user_genres: list[str]) -> float:
    """Jaccard similarity between movie genres and user's favorite genres."""
    if not user_genres or not movie_genres:
        return 0.0
    movie_set = {g.get("name", "").lower() for g in movie_genres if g.get("name")}
    user_set = {g.lower() for g in user_genres}
    intersection = movie_set & user_set
    union = movie_set | user_set
    if not union:
        return 0.0
    return len(intersection) / len(union)


def _consensus_score(vote_average: float | None) -> float:
    """Normalize TMDB vote_average (0-10) to 0-1."""
    if vote_average is None:
        return 0.0
    return min(vote_average / 10.0, 1.0)


def _director_boost(movie_director: str | None, top_directors: set[str]) -> float:
    """1.0 if movie's director is in user's top directors, else 0."""
    if not movie_director or not top_directors:
        return 0.0
    return 1.0 if movie_director.lower() in top_directors else 0.0


def _cast_boost(movie_cast: list[dict], top_cast: set[str]) -> float:
    """Fraction of movie's cast that appears in user's top cast names."""
    if not movie_cast or not top_cast:
        return 0.0
    movie_names = {c.get("name", "").lower() for c in movie_cast if c.get("name")}
    if not movie_names:
        return 0.0
    return len(movie_names & top_cast) / len(movie_names)


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    va, vb = np.array(a), np.array(b)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def rerank_candidates(
    candidates: list[dict],
    user_genres: list[str],
    top_directors: set[str],
    top_cast: set[str],
    negative_embedding: list[float] | None = None,
    candidate_embeddings: dict[int, list[float]] | None = None,
) -> list[dict]:
    """Re-rank pgvector candidates using structured signals + negative penalty.

    Each candidate dict must have keys: "movie" (Movie), "similarity" (float), "tmdb_id" (int).
    Returns candidates sorted by final score descending, with "score" added to each.
    """
    for c in candidates:
        movie: Movie = c["movie"]
        sim = c["similarity"]

        genre = _genre_overlap(movie.genres or [], user_genres)
        consensus = _consensus_score(movie.vote_average)
        director = _director_boost(movie.director, top_directors)
        cast = _cast_boost(movie.cast or [], top_cast)

        score = (
            W_SIMILARITY * sim
            + W_GENRE * genre
            + W_CONSENSUS * consensus
            + W_DIRECTOR * director
            + W_CAST * cast
        )

        # Negative penalty: subtract similarity to negative embedding
        if negative_embedding and candidate_embeddings:
            emb = candidate_embeddings.get(c["tmdb_id"])
            if emb:
                neg_sim = _cosine_sim(emb, negative_embedding)
                score -= W_NEGATIVE * max(neg_sim, 0.0)

        c["score"] = round(max(score, 0.0), 4)

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return _shuffle_within_tiers(candidates)


# Candidates with scores within this threshold are considered the same tier
TIER_THRESHOLD = 0.02


def _shuffle_within_tiers(candidates: list[dict]) -> list[dict]:
    """Shuffle candidates within score tiers for variety.

    Groups candidates whose scores are within TIER_THRESHOLD of each other,
    then shuffles within each group. Preserves inter-tier ordering.
    """
    if not candidates:
        return candidates

    result: list[dict] = []
    tier: list[dict] = [candidates[0]]

    for c in candidates[1:]:
        if tier[0]["score"] - c["score"] <= TIER_THRESHOLD:
            tier.append(c)
        else:
            random.shuffle(tier)
            result.extend(tier)
            tier = [c]

    random.shuffle(tier)
    result.extend(tier)
    return result


SAMPLE_TEMPERATURE = 1.0  # Tunable: 0.5 = conservative, 2.0 = exploratory
EXPLORE_TEMPERATURE = 1.5  # Higher for exploration diversity
SAMPLE_SIZE = 200  # How many to sample from the over-fetched pool


def probabilistic_sample(
    candidates: list[dict],
    sample_size: int = SAMPLE_SIZE,
    temperature: float = SAMPLE_TEMPERATURE,
) -> list[dict]:
    """Softmax-weighted sampling from candidates. Higher scores = higher probability."""
    if len(candidates) <= sample_size:
        return candidates

    scores = np.array([c["score"] for c in candidates])
    # Softmax with temperature (subtract max for numerical stability)
    shifted = scores - scores.max()
    exp_scores = np.exp(shifted / temperature)
    probabilities = exp_scores / exp_scores.sum()

    # Sample without replacement
    indices = np.random.choice(
        len(candidates), size=sample_size, replace=False, p=probabilities
    )
    sampled = [candidates[i] for i in indices]
    # Re-sort by score descending
    sampled.sort(key=lambda c: c["score"], reverse=True)
    return sampled


MATCH_BOOST = 0.33


def to_match_percentage(score: float) -> float:
    """Shift raw score up by MATCH_BOOST, capped at 1.0."""
    return round(min(score + MATCH_BOOST, 1.0), 4)


def score_exploration(
    movie: Movie,
    genre_freq: dict[str, float],
    total_watches: int,
) -> float:
    """Score a movie for exploration: novelty + consensus + trending."""
    # Genre novelty: 1 - familiarity (most familiar genre in this movie)
    movie_genres = [
        g.get("name", "").lower() for g in (movie.genres or []) if g.get("name")
    ]
    if movie_genres and total_watches > 0:
        familiarity = max(genre_freq.get(g, 0.0) for g in movie_genres)
        novelty = 1.0 - familiarity
    else:
        novelty = 1.0  # No watches = everything is novel

    consensus = _consensus_score(movie.vote_average)

    # Trending: recency based on release year
    current_year = datetime.now(timezone.utc).year
    if movie.year:
        age_ratio = min((current_year - movie.year) / 10, 1.0)
        trending = max(0.0, 1.0 - age_ratio)
    else:
        trending = 0.0

    return round(
        W_NOVELTY * novelty + W_CONSENSUS_EXPLORE * consensus + W_TRENDING * trending,
        4,
    )
