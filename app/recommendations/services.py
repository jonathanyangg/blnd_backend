import logging

import numpy as np
from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.import_data.models import MovieEmbedding
from app.movies.models import Movie
from app.recommendations.ranking import rerank_candidates
from app.tracking.models import WatchedMovie

logger = logging.getLogger(__name__)


def get_top_rated_movies(user_id: str, db: Session, limit: int = 25) -> list[dict]:
    """Get user's top-rated watched movies joined with movie details."""
    rows = (
        db.query(WatchedMovie, Movie)
        .join(Movie, WatchedMovie.tmdb_id == Movie.tmdb_id)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.rating.isnot(None))
        .order_by(WatchedMovie.rating.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "title": movie.title,
            "year": movie.year,
            "overview": movie.overview,
            "genres": [g.get("name", "") for g in (movie.genres or [])],
            "director": movie.director,
            "cast": [c.get("name", "") for c in (movie.cast or [])[:3]],
            "rating": watched.rating,
        }
        for watched, movie in rows
    ]


def get_user_signal_context(
    user_id: str, db: Session
) -> tuple[list[str], set[str], set[str]]:
    """Extract user's favorite genres, top directors, and top cast from their top-rated movies.

    Returns (favorite_genres, top_directors_lowered, top_cast_lowered).
    """
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    favorite_genres = (
        profile.favorite_genres if profile and profile.favorite_genres else []
    )

    # Get top 10 rated movies for director/cast signals
    rows = (
        db.query(Movie)
        .join(WatchedMovie, WatchedMovie.tmdb_id == Movie.tmdb_id)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.rating.isnot(None))
        .order_by(WatchedMovie.rating.desc())
        .limit(10)
        .all()
    )

    top_directors: set[str] = set()
    top_cast: set[str] = set()
    for movie in rows:
        if movie.director:
            top_directors.add(movie.director.lower())
        for c in (movie.cast or [])[:5]:
            name = c.get("name", "")
            if name:
                top_cast.add(name.lower())

    return favorite_genres, top_directors, top_cast


def build_taste_prompt(
    favorite_genres: list[str] | None, movies: list[dict]
) -> str | None:
    """Build a prompt for LLM taste bio generation."""
    if not movies:
        return None

    parts: list[str] = []

    if favorite_genres:
        parts.append(f"Favorite genres: {', '.join(favorite_genres)}")

    parts.append("Top rated movies:")
    for m in movies:
        line = f"- {m['title']}"
        if m.get("year"):
            line += f" ({m['year']})"
        if m.get("director"):
            line += f" dir. {m['director']}"
        if m.get("rating"):
            line += f" [rated {m['rating']}/5]"
        if m.get("genres"):
            line += f" | {', '.join(m['genres'])}"
        if m.get("cast"):
            line += f" | starring {', '.join(m['cast'])}"
        parts.append(line)

    return "\n".join(parts)


def generate_taste_bio(prompt: str, openai_client: OpenAI) -> str:
    """Use gpt-4o-mini to generate a semantic taste description."""
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a movie description writer. Given a user's movie preferences, "
                    "write a fictional movie overview/synopsis that perfectly captures "
                    "the themes, genres, tone, and storytelling style they love. "
                    "Write it exactly like a movie plot summary — with characters, "
                    "a setting, and a narrative arc. Do NOT describe the user's taste. "
                    "Instead, describe the IDEAL movie for this person. "
                    "Keep it to 2-3 paragraphs, like a movie overview on TMDB."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=500,
        temperature=0.7,
    )
    return response.choices[0].message.content or ""


def embed_taste_bio(taste_bio: str, openai_client: OpenAI) -> list[float]:
    """Embed taste bio with text-embedding-3-small (same model as movie embeddings)."""
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=taste_bio,
    )
    return response.data[0].embedding


# --- Embedding strategy: "average" or "llm" ---
EMBEDDING_STRATEGY = "average"


def compute_average_embedding(user_id: str, db: Session) -> list[float] | None:
    """Average the embeddings of the user's top-rated movies, weighted by rating."""
    rows = (
        db.query(WatchedMovie.rating, MovieEmbedding.embedding)
        .join(MovieEmbedding, WatchedMovie.tmdb_id == MovieEmbedding.tmdb_id)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.rating.isnot(None))
        .order_by(WatchedMovie.rating.desc())
        .limit(25)
        .all()
    )
    if not rows:
        return None

    ratings = np.array([float(r) for r, _ in rows])
    embeddings = np.array([e for _, e in rows])

    if ratings.sum() == 0:
        return None

    weighted_avg = np.average(embeddings, axis=0, weights=ratings)
    return weighted_avg.tolist()


def rebuild_taste_profile(
    user_id: str, db: Session, openai_client: OpenAI
) -> Profile | None:
    """Orchestrator: build taste embedding + generate taste bio for display."""
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        return None

    movies = get_top_rated_movies(user_id, db)

    # Taste embedding: switch between strategies
    if EMBEDDING_STRATEGY == "average":
        taste_embedding = compute_average_embedding(user_id, db)
        if not taste_embedding:
            raise Exception("User has no movies rated yet")
        profile.taste_embedding = taste_embedding
    else:
        # LLM strategy: embed the generated taste bio
        prompt = build_taste_prompt(profile.favorite_genres, movies)
        if not prompt:
            prompt = ""
        taste_bio = generate_taste_bio(prompt, openai_client)
        taste_embedding = embed_taste_bio(taste_bio, openai_client)
        profile.taste_bio = taste_bio
        profile.taste_embedding = taste_embedding

    db.commit()
    db.refresh(profile)

    logger.info(
        "Rebuilt taste profile for user %s (strategy=%s)", user_id, EMBEDDING_STRATEGY
    )
    return profile


CANDIDATE_POOL_SIZE = 200


def get_recommendations(
    user_id: str,
    db: Session,
    openai_client: OpenAI,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Get movie recommendations via pgvector similarity + re-ranking."""
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        return {"results": [], "taste_bio": None}

    # Build taste profile inline if missing
    if profile.taste_embedding is None:
        profile = rebuild_taste_profile(user_id, db, openai_client)
        if not profile or profile.taste_embedding is None:
            return {"results": [], "taste_bio": profile.taste_bio if profile else None}

    # Get watched movie IDs to exclude
    watched_ids = [
        row[0]
        for row in db.query(WatchedMovie.tmdb_id)
        .filter(WatchedMovie.user_id == user_id)
        .all()
    ]

    # Over-fetch candidates from pgvector
    embedding_str = "[" + ",".join(str(v) for v in profile.taste_embedding) + "]"

    result = db.execute(
        text(
            "SELECT * FROM match_movies("
            "cast(:query_embedding AS vector(1536)), :match_count, :exclude_ids"
            ")"
        ),
        {
            "query_embedding": embedding_str,
            "match_count": CANDIDATE_POOL_SIZE,
            "exclude_ids": watched_ids if watched_ids else [],
        },
    )
    rows = result.fetchall()

    if not rows:
        return {"results": [], "taste_bio": profile.taste_bio}

    # Build candidate list with full movie objects
    tmdb_ids = [row[0] for row in rows]
    similarity_map = {row[0]: row[1] for row in rows}

    movies = db.query(Movie).filter(Movie.tmdb_id.in_(tmdb_ids)).all()
    movie_map = {m.tmdb_id: m for m in movies}

    candidates = []
    for tmdb_id in tmdb_ids:
        movie = movie_map.get(tmdb_id)
        if not movie:
            continue
        candidates.append(
            {
                "tmdb_id": tmdb_id,
                "similarity": similarity_map[tmdb_id],
                "movie": movie,
            }
        )

    # Re-rank with structured signals
    user_genres, top_directors, top_cast = get_user_signal_context(user_id, db)
    ranked = rerank_candidates(candidates, user_genres, top_directors, top_cast)

    # Apply pagination
    page = ranked[offset : offset + limit]

    results = []
    for c in page:
        movie = c["movie"]
        results.append(
            {
                "tmdb_id": movie.tmdb_id,
                "title": movie.title,
                "year": movie.year,
                "overview": movie.overview,
                "poster_path": movie.poster_path,
                "genres": movie.genres or [],
                "director": movie.director,
                "similarity": round(c["similarity"], 4),
                "score": c["score"],
            }
        )

    return {"results": results, "taste_bio": profile.taste_bio}
