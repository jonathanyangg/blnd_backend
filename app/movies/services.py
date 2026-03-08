import numpy as np
import httpx
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.import_data.models import MovieEmbedding
from app.movies.models import Movie
from app.recommendations.ranking import (
    W_CAST,
    W_CONSENSUS,
    W_DIRECTOR,
    W_GENRE,
    W_SIMILARITY,
    _cast_boost,
    _consensus_score,
    _director_boost,
    _genre_overlap,
    to_match_percentage,
)
from app.recommendations.services import get_user_signal_context


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _compute_score(
    movie: Movie,
    similarity: float,
    user_genres: list[str],
    top_directors: set[str],
    top_cast: set[str],
) -> float:
    genre = _genre_overlap(movie.genres or [], user_genres)
    consensus = _consensus_score(movie.vote_average)
    director = _director_boost(movie.director, top_directors)
    cast = _cast_boost(movie.cast or [], top_cast)
    return round(
        W_SIMILARITY * similarity
        + W_GENRE * genre
        + W_CONSENSUS * consensus
        + W_DIRECTOR * director
        + W_CAST * cast,
        4,
    )


def compute_match_scores(
    tmdb_ids: list[int], user_id: str, db: Session
) -> dict[int, float]:
    """Compute match scores for a list of movies against a user's taste profile.

    Returns {tmdb_id: score} for movies that have embeddings. Missing ones are omitted.
    """
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile or profile.taste_embedding is None:
        return {}

    taste_emb = list(profile.taste_embedding)

    # Batch-fetch embeddings
    embeddings = (
        db.query(MovieEmbedding).filter(MovieEmbedding.tmdb_id.in_(tmdb_ids)).all()
    )
    emb_map = {e.tmdb_id: list(e.embedding) for e in embeddings}

    # Batch-fetch movie records for ranking signals
    movies = db.query(Movie).filter(Movie.tmdb_id.in_(tmdb_ids)).all()
    movie_map = {m.tmdb_id: m for m in movies}

    user_genres, top_directors, top_cast = get_user_signal_context(user_id, db)

    scores: dict[int, float] = {}
    for tid in tmdb_ids:
        movie_emb = emb_map.get(tid)
        movie = movie_map.get(tid)
        if not movie_emb or not movie:
            continue
        similarity = _cosine_similarity(taste_emb, movie_emb)
        raw = _compute_score(movie, similarity, user_genres, top_directors, top_cast)
        scores[tid] = to_match_percentage(raw)

    return scores


TMDB_GENRE_MAP = {
    "action": 28,
    "comedy": 35,
    "horror": 27,
    "sci-fi": 878,
    "romance": 10749,
    "thriller": 53,
    "drama": 18,
    "animation": 16,
    "documentary": 99,
    "mystery": 9648,
    "fantasy": 14,
    "crime": 80,
}


async def discover_movies_by_genres(
    genre_names: list[str], page: int, tmdb_client: httpx.AsyncClient
) -> dict:
    """Discover top-rated movies matching the given genres via TMDB discover API."""
    genre_ids = []
    for name in genre_names:
        gid = TMDB_GENRE_MAP.get(name.lower())
        if gid:
            genre_ids.append(str(gid))

    if not genre_ids:
        return {"results": [], "total_results": 0}

    response = await tmdb_client.get(
        "/discover/movie",
        params={
            "with_genres": "|".join(genre_ids),
            "sort_by": "vote_count.desc",
            "vote_average.gte": 6.0,
            "page": page,
        },
    )
    response.raise_for_status()
    data = response.json()

    results = []
    for item in data.get("results", []):
        year = None
        if item.get("release_date"):
            try:
                year = int(item["release_date"][:4])
            except (ValueError, IndexError):
                pass

        results.append(
            {
                "tmdb_id": item["id"],
                "title": item["title"],
                "year": year,
                "overview": item.get("overview"),
                "poster_path": item.get("poster_path"),
                "genres": [{"id": gid} for gid in item.get("genre_ids", [])],
                "vote_average": item.get("vote_average"),
            }
        )

    return {"results": results, "total_results": data.get("total_results", 0)}


async def get_trending_movies(page: int, tmdb_client: httpx.AsyncClient) -> dict:
    """Get trending movies from TMDB (weekly)."""
    response = await tmdb_client.get("/trending/movie/week", params={"page": page})
    response.raise_for_status()
    data = response.json()

    results = []
    for item in data.get("results", []):
        year = None
        if item.get("release_date"):
            try:
                year = int(item["release_date"][:4])
            except (ValueError, IndexError):
                pass

        results.append(
            {
                "tmdb_id": item["id"],
                "title": item["title"],
                "year": year,
                "overview": item.get("overview"),
                "poster_path": item.get("poster_path"),
                "genres": [{"id": gid} for gid in item.get("genre_ids", [])],
                "vote_average": item.get("vote_average"),
            }
        )

    return {"results": results, "total_results": data.get("total_results", 0)}


async def search_movies(query: str, page: int, tmdb_client: httpx.AsyncClient) -> dict:
    """Search TMDB for movies. No caching — results change over time."""
    response = await tmdb_client.get(
        "/search/movie", params={"query": query, "page": page}
    )
    response.raise_for_status()
    data = response.json()

    results = []
    for item in data.get("results", []):
        year = None
        if item.get("release_date"):
            try:
                year = int(item["release_date"][:4])
            except (ValueError, IndexError):
                pass

        results.append(
            {
                "tmdb_id": item["id"],
                "title": item["title"],
                "year": year,
                "overview": item.get("overview"),
                "poster_path": item.get("poster_path"),
                "genres": [{"id": gid} for gid in item.get("genre_ids", [])],
                "vote_average": item.get("vote_average"),
            }
        )

    return {"results": results, "total_results": data.get("total_results", 0)}


async def get_movie_details(
    tmdb_id: int, db: Session, tmdb_client: httpx.AsyncClient
) -> Movie:
    """Get movie details — returns from DB cache or fetches from TMDB."""
    cached = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
    if cached:
        return cached

    # Fetch movie details + credits + videos in one call
    response = await tmdb_client.get(
        f"/movie/{tmdb_id}", params={"append_to_response": "credits,videos"}
    )
    response.raise_for_status()
    tmdb_data = response.json()

    movie = _cache_movie_from_tmdb(tmdb_data, db)
    return movie


def _cache_movie_from_tmdb(tmdb_data: dict, db: Session) -> Movie:
    """Parse TMDB response (with appended credits/videos) into a Movie record."""
    year = None
    if tmdb_data.get("release_date"):
        try:
            year = int(tmdb_data["release_date"][:4])
        except (ValueError, IndexError):
            pass

    genres = [{"id": g["id"], "name": g["name"]} for g in tmdb_data.get("genres", [])]

    # Extract director from credits.crew
    director = None
    credits = tmdb_data.get("credits", {})
    for crew_member in credits.get("crew", []):
        if crew_member.get("job") == "Director":
            director = crew_member["name"]
            break

    # Extract top 5 cast
    cast_list = [
        {"name": c["name"], "character": c.get("character", "")}
        for c in credits.get("cast", [])[:5]
    ]

    # Extract trailer from videos
    trailer_url = _extract_trailer_url(tmdb_data.get("videos", {}))

    movie = Movie(
        tmdb_id=tmdb_data["id"],
        title=tmdb_data["title"],
        year=year,
        overview=tmdb_data.get("overview"),
        poster_path=tmdb_data.get("poster_path"),
        genres=genres,
        runtime=tmdb_data.get("runtime"),
        vote_average=tmdb_data.get("vote_average"),
        trailer_url=trailer_url,
        director=director,
        cast=cast_list,
        tagline=tmdb_data.get("tagline") or None,
        backdrop_path=tmdb_data.get("backdrop_path"),
        imdb_id=tmdb_data.get("imdb_id"),
    )
    db.add(movie)
    db.commit()
    db.refresh(movie)
    return movie


def _extract_trailer_url(videos_data: dict) -> str | None:
    """Extract YouTube trailer URL from TMDB videos response."""
    for video in videos_data.get("results", []):
        if video.get("site") == "YouTube" and video.get("type") == "Trailer":
            return f"https://www.youtube.com/watch?v={video['key']}"
    return None
