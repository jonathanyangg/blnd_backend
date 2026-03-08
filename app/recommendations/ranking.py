"""Re-ranking layer for recommendation candidates.

Architecture: pgvector returns ~200 candidates by cosine similarity,
then this module re-ranks using structured signals (genre, consensus, director, cast).
"""

from app.movies.models import Movie

# Weights — easy to tune later
W_SIMILARITY = 0.50
W_GENRE = 0.20
W_CONSENSUS = 0.20
W_DIRECTOR = 0.05
W_CAST = 0.05


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


def rerank_candidates(
    candidates: list[dict],
    user_genres: list[str],
    top_directors: set[str],
    top_cast: set[str],
) -> list[dict]:
    """Re-rank pgvector candidates using structured signals.

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

        c["score"] = round(
            W_SIMILARITY * sim
            + W_GENRE * genre
            + W_CONSENSUS * consensus
            + W_DIRECTOR * director
            + W_CAST * cast,
            4,
        )

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


MATCH_BOOST = 0.4


def to_match_percentage(score: float) -> float:
    """Scale raw score to 0–1 with upward compression."""
    return round(score + (1 - score) * MATCH_BOOST, 4)
