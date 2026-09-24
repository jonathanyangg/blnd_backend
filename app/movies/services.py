import logging

import httpx
import numpy as np
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.import_data.models import MovieEmbedding
from app.movies.models import Movie
from app.recommendations.collaborative import compute_cf_scores
from app.recommendations.ranking import (
    W_CAST,
    W_CONSENSUS,
    W_DIRECTOR,
    W_GENRE,
    W_NEGATIVE,
    W_SIMILARITY,
    _cast_boost,
    _consensus_score,
    _cosine_sim,
    _director_boost,
    _genre_overlap,
    to_match_percentage,
)
from app.recommendations.services import (
    NEGATIVE_RATING_MIN_MOVIES,
    NEGATIVE_RATING_PERCENTILE,
    WATCHLIST_WEIGHT,
    get_user_signal_context,
)
from app.tracking.models import WatchedMovie, WatchlistMovie

logger = logging.getLogger(__name__)


def _compute_score(
    movie: Movie,
    similarity: float,
    user_genres: list[str],
    top_directors: set[str],
    top_cast: set[str],
    negative_sim: float = 0.0,
) -> float:
    genre = _genre_overlap(movie.genres or [], user_genres)
    consensus = _consensus_score(movie.vote_average)
    director = _director_boost(movie.director, top_directors)
    cast = _cast_boost(movie.cast or [], top_cast)
    score = (
        W_SIMILARITY * similarity
        + W_GENRE * genre
        + W_CONSENSUS * consensus
        + W_DIRECTOR * director
        + W_CAST * cast
        - W_NEGATIVE * max(negative_sim, 0.0)
    )
    return round(max(score, 0.0), 4)


def _contribution_weights(
    tmdb_ids: list[int], user_id: str, profile: Profile, db: Session
) -> dict[int, float]:
    """Return {tmdb_id: weight} for any scored movie that contributed to the
    user's positive taste embedding — rated at/above the 20th-percentile
    threshold (weight = rating) or currently in the user's watchlist
    (weight = WATCHLIST_WEIGHT). Movies not in the map contributed 0.
    """
    weights: dict[int, float] = {}

    # Fetch all user's ratings once so we can compute the same percentile
    # threshold that compute_taste_embeddings uses.
    all_ratings_rows = (
        db.query(WatchedMovie.tmdb_id, WatchedMovie.rating)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.rating.isnot(None))
        .all()
    )
    if all_ratings_rows:
        all_ratings = np.array([float(r) for _, r in all_ratings_rows])
        if len(all_ratings) >= NEGATIVE_RATING_MIN_MOVIES:
            threshold = float(np.percentile(all_ratings, NEGATIVE_RATING_PERCENTILE))
        else:
            threshold = 0.0  # <10 ratings: every rated movie is positive
        scored_set = set(tmdb_ids)
        for tid, rating in all_ratings_rows:
            if tid in scored_set:
                r = float(rating)
                if r >= threshold:
                    weights[tid] = r

    if profile.watchlist_id:
        wl_rows = (
            db.query(WatchlistMovie.tmdb_id)
            .filter(
                WatchlistMovie.watchlist_id == profile.watchlist_id,
                WatchlistMovie.tmdb_id.in_(tmdb_ids),
            )
            .all()
        )
        for (tid,) in wl_rows:
            # Rated movies are auto-removed from watchlist, so no overlap —
            # but defensively take the max if somehow both apply.
            weights[tid] = max(weights.get(tid, 0.0), WATCHLIST_WEIGHT)

    return weights


def compute_match_scores(
    tmdb_ids: list[int], user_id: str, db: Session
) -> dict[int, float]:
    """Compute match scores for a list of movies against a user's taste profile.

    Returns {tmdb_id: score} for every movie in the list that has a Movie record.
    The similarity term is the collaborative-filtering prediction when the
    movie has enough co-rating support, otherwise the taste-embedding cosine.
    When a movie has neither, falls back to a genre+consensus-only score
    (similarity term becomes 0, remaining signals renormalized so the
    fallback can still reach ~100%).

    For movies that contributed to the user's taste embedding (rated positive or
    currently in watchlist), we apply a leave-one-out adjustment so a movie isn't
    being compared against a taste vector that contains itself.
    """
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile or profile.taste_embedding is None:
        return {}

    taste_emb = np.array(profile.taste_embedding, dtype=np.float64)
    negative_emb = (
        list(profile.negative_embedding)
        if profile.negative_embedding is not None
        else None
    )
    sum_weights = profile.taste_sum_weights

    # Batch-fetch embeddings
    embeddings = (
        db.query(MovieEmbedding).filter(MovieEmbedding.tmdb_id.in_(tmdb_ids)).all()
    )
    emb_map = {e.tmdb_id: list(e.embedding) for e in embeddings}

    # Batch-fetch movie records for ranking signals
    movies = db.query(Movie).filter(Movie.tmdb_id.in_(tmdb_ids)).all()
    movie_map = {m.tmdb_id: m for m in movies}

    user_genres, top_directors, top_cast = get_user_signal_context(user_id, db)
    cf_scores = compute_cf_scores([user_id], tmdb_ids, db)

    # Per-movie contribution weights for leave-one-out (only when sum_weights
    # is present — LLM-strategy taste embeddings don't support this).
    contrib_weights = (
        _contribution_weights(tmdb_ids, user_id, profile, db)
        if sum_weights and sum_weights > 0
        else {}
    )

    # Renormalization factor for fallback (drops W_SIMILARITY and W_NEGATIVE)
    fallback_denom = W_GENRE + W_CONSENSUS + W_DIRECTOR + W_CAST

    scores: dict[int, float] = {}
    for tid in tmdb_ids:
        movie = movie_map.get(tid)
        if not movie:
            continue
        movie_emb = emb_map.get(tid)
        similarity = cf_scores.get(tid)
        if similarity is None and movie_emb:
            movie_weight = contrib_weights.get(tid, 0.0)
            if movie_weight > 0 and sum_weights and sum_weights > movie_weight:
                # Leave-one-out: reconstruct the taste vector without this
                # movie's own contribution before taking cosine similarity.
                adjusted_denom = sum_weights - movie_weight
                adjusted_taste = (
                    taste_emb * sum_weights
                    - movie_weight * np.array(movie_emb, dtype=np.float64)
                ) / adjusted_denom
                similarity = _cosine_sim(adjusted_taste.tolist(), movie_emb)
            else:
                similarity = _cosine_sim(taste_emb.tolist(), movie_emb)

        if similarity is not None:
            neg_sim = (
                _cosine_sim(movie_emb, negative_emb)
                if movie_emb and negative_emb
                else 0.0
            )
            raw = _compute_score(
                movie, similarity, user_genres, top_directors, top_cast, neg_sim
            )
        else:
            # Fallback: no CF support and no embedding. Use other signals only.
            genre = _genre_overlap(movie.genres or [], user_genres)
            consensus = _consensus_score(movie.vote_average)
            director = _director_boost(movie.director, top_directors)
            cast = _cast_boost(movie.cast or [], top_cast)
            weighted = (
                W_GENRE * genre
                + W_CONSENSUS * consensus
                + W_DIRECTOR * director
                + W_CAST * cast
            )
            raw = round(max(weighted / fallback_denom, 0.0), 4)
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


def _parse_tmdb_results(data: dict) -> list[dict]:
    """Parse TMDB list response into standardized movie dicts."""
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
    return results


def enrich_from_cache(results: list[dict], db: Session) -> tuple[list[dict], list[int]]:
    """Enrich movie dicts with cached detail data (trailer, cast, etc).

    Returns (enriched_results, uncached_tmdb_ids).
    """
    tmdb_ids = [r["tmdb_id"] for r in results]
    cached = db.query(Movie).filter(Movie.tmdb_id.in_(tmdb_ids)).all()
    cache_map = {m.tmdb_id: m for m in cached}

    uncached_ids = []
    for result in results:
        movie = cache_map.get(result["tmdb_id"])
        if movie:
            result["trailer_url"] = movie.trailer_url
            result["cast"] = movie.cast or []
            result["director"] = movie.director
            result["runtime"] = movie.runtime
            result["tagline"] = movie.tagline
            result["backdrop_path"] = movie.backdrop_path
            if movie.genres:
                result["genres"] = movie.genres
        else:
            uncached_ids.append(result["tmdb_id"])

    return results, uncached_ids


async def cache_movies_in_background(uncached_ids: list[int]) -> None:
    """Fetch and cache movie details for uncached IDs. Runs as a background task."""
    from app.config import settings
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        async with httpx.AsyncClient(
            base_url="https://api.themoviedb.org/3",
            headers={"Authorization": f"Bearer {settings.tmdb_api_key}"},
            timeout=30,
        ) as client:
            for tmdb_id in uncached_ids:
                # Skip if another request cached it in the meantime
                if db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first():
                    continue
                try:
                    resp = await client.get(
                        f"/movie/{tmdb_id}",
                        params={"append_to_response": "credits,videos"},
                    )
                    resp.raise_for_status()
                    _cache_movie_from_tmdb(resp.json(), db)
                except Exception:
                    logger.warning("Background cache failed for tmdb_id=%s", tmdb_id)
                    db.rollback()
    finally:
        db.close()


async def discover_movies_by_genres(
    genre_names: list[str],
    tmdb_client: httpx.AsyncClient,
    exclude: set[int] | None = None,
) -> dict:
    """Discover movies matching the given genres with probabilistic sampling."""
    from app.movies.sampling import fetch_and_sample

    genre_ids = []
    for name in genre_names:
        gid = TMDB_GENRE_MAP.get(name.lower())
        if gid:
            genre_ids.append(str(gid))

    if not genre_ids:
        return {"results": [], "total_results": 0}

    async def fetch_page(page: int) -> list[dict]:
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
        return _parse_tmdb_results(response.json())

    return await fetch_and_sample(fetch_page, exclude=exclude)


async def search_people(query: str, page: int, tmdb_client: httpx.AsyncClient) -> dict:
    """Search TMDB for people. Filters to actors only."""
    response = await tmdb_client.get(
        "/search/person", params={"query": query, "page": page}
    )
    response.raise_for_status()
    data = response.json()

    results = []
    for item in data.get("results", []):
        if item.get("known_for_department") != "Acting":
            continue
        results.append(
            {
                "id": item["id"],
                "name": item["name"],
                "profile_path": item.get("profile_path"),
                "known_for_department": item.get("known_for_department"),
                "popularity": item.get("popularity"),
            }
        )

    results.sort(key=lambda x: x.get("popularity") or 0, reverse=True)
    return {"results": results, "total_results": len(results)}


async def discover_movies_by_actor(
    person_id: int,
    tmdb_client: httpx.AsyncClient,
    exclude: set[int] | None = None,
    genre_names: list[str] | None = None,
) -> dict:
    """Discover movies featuring a specific actor with probabilistic sampling."""
    from app.movies.sampling import SAMPLE_SIZE, fetch_and_sample

    params: dict[str, str | int | float] = {
        "with_cast": person_id,
        "sort_by": "vote_count.desc",
        "vote_average.gte": 5.0,
    }

    if genre_names:
        genre_ids = [
            str(TMDB_GENRE_MAP[n.lower()])
            for n in genre_names
            if n.lower() in TMDB_GENRE_MAP
        ]
        if genre_ids:
            params["with_genres"] = "|".join(genre_ids)

    async def fetch_page(page: int) -> list[dict]:
        response = await tmdb_client.get(
            "/discover/movie",
            params={**params, "page": page},
        )
        response.raise_for_status()
        return _parse_tmdb_results(response.json())

    # Probe first page to determine filmography size
    first_page = await fetch_page(1)
    pool_estimate = len(first_page)
    pages = 3 if pool_estimate < SAMPLE_SIZE else 5

    return await fetch_and_sample(fetch_page, pages=pages, exclude=exclude)


async def get_top_rated_movies(
    tmdb_client: httpx.AsyncClient, exclude: set[int] | None = None
) -> dict:
    """Get top-rated movies from TMDB with probabilistic sampling."""
    from app.movies.sampling import fetch_and_sample

    async def fetch_page(page: int) -> list[dict]:
        response = await tmdb_client.get("/movie/top_rated", params={"page": page})
        response.raise_for_status()
        return _parse_tmdb_results(response.json())

    return await fetch_and_sample(fetch_page, exclude=exclude)


async def get_trending_movies(
    tmdb_client: httpx.AsyncClient, exclude: set[int] | None = None
) -> dict:
    """Get trending movies from TMDB (weekly) with probabilistic sampling."""
    from app.movies.sampling import fetch_and_sample

    async def fetch_page(page: int) -> list[dict]:
        response = await tmdb_client.get("/trending/movie/week", params={"page": page})
        response.raise_for_status()
        return _parse_tmdb_results(response.json())

    return await fetch_and_sample(fetch_page, exclude=exclude)


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

    # Extract top 5 cast (with profile photos for frontend avatars)
    cast_list = [
        {
            "id": c["id"],
            "name": c["name"],
            "character": c.get("character", ""),
            "profile_path": c.get("profile_path"),
        }
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


def embed_movie_in_background(tmdb_id: int) -> None:
    """Generate a MovieEmbedding for a single movie. Runs in a background task.

    Fired when a detail view request finds a Movie without an embedding
    (typically from search/new releases not covered by the seed pipeline).
    Idempotent — exits early if the embedding already exists.
    """
    from app.database import SessionLocal
    from app.dependencies import openai_client

    db = SessionLocal()
    try:
        # Sanity dedup — another request may have embedded it already
        existing = (
            db.query(MovieEmbedding).filter(MovieEmbedding.tmdb_id == tmdb_id).first()
        )
        if existing:
            return

        movie = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
        if not movie or not movie.overview:
            return

        text = (
            f"{movie.title} ({movie.year}): {movie.overview}"
            if movie.year
            else f"{movie.title}: {movie.overview}"
        )

        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=[text],
        )
        embedding = response.data[0].embedding

        db.add(MovieEmbedding(tmdb_id=tmdb_id, embedding=embedding))
        db.commit()
        logger.info("Background-embedded movie tmdb_id=%s", tmdb_id)
    except Exception:
        logger.warning("Background embed failed for tmdb_id=%s", tmdb_id, exc_info=True)
        db.rollback()
    finally:
        db.close()
