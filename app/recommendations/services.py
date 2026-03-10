import logging

import numpy as np
from openai import OpenAI
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.import_data.models import MovieEmbedding
from app.movies.models import Movie
from app.recommendations.models import HiddenMovie
from app.tracking.models import WatchedMovie

logger = logging.getLogger(__name__)

AUTO_REBUILD_THRESHOLD = 50


def should_auto_rebuild(user_id: str, db: Session) -> bool:
    """Decide whether to auto-rebuild taste profile after a rating change.

    Always rebuild if user has <50 rated movies (still learning).
    Never auto-rebuild if 50+ (manual refresh only).
    """
    count = (
        db.query(WatchedMovie)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.rating.isnot(None))
        .count()
    )
    return count < AUTO_REBUILD_THRESHOLD


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


def compute_taste_embeddings(
    user_id: str, db: Session
) -> tuple[list[float] | None, list[float] | None]:
    """Compute taste embeddings using rating-weighted average.

    Positive embedding: weighted average of all rated movies, weight = rating.
    Higher-rated movies pull the taste vector more strongly. Low-rated movies
    have minimal influence without needing an arbitrary positive/negative split.

    Negative embedding: only from explicitly hidden movies (user said "don't
    show me this"). We don't infer negativity from ratings — a 3.5/5 is not
    a dislike signal.

    Returns (positive_embedding, negative_embedding).
    """
    rows = (
        db.query(WatchedMovie.tmdb_id, WatchedMovie.rating, MovieEmbedding.embedding)
        .join(MovieEmbedding, WatchedMovie.tmdb_id == MovieEmbedding.tmdb_id)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.rating.isnot(None))
        .all()
    )
    if not rows:
        return None, None

    ratings = np.array([float(r) for _, r, _ in rows])
    embeddings = np.array([e for _, _, e in rows])

    # Weight = rating value directly (0.5–5.0). A 5-star movie has 10x the
    # pull of a 0.5-star movie. Simple, interpretable, no threshold needed.
    positive_emb = np.average(embeddings, axis=0, weights=ratings).tolist()

    # Negative embedding: only from hidden movies (explicit signal)
    negative_emb = None
    hidden_rows = (
        db.query(MovieEmbedding.embedding)
        .join(HiddenMovie, HiddenMovie.tmdb_id == MovieEmbedding.tmdb_id)
        .filter(HiddenMovie.user_id == user_id)
        .all()
    )
    if hidden_rows:
        hidden_embeddings = np.array([e for (e,) in hidden_rows])
        negative_emb = np.mean(hidden_embeddings, axis=0).tolist()

    return positive_emb, negative_emb


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
        positive_emb, negative_emb = compute_taste_embeddings(user_id, db)
        if not positive_emb:
            raise Exception("User has no movies rated yet")
        profile.taste_embedding = positive_emb
        profile.negative_embedding = negative_emb
    else:
        # LLM strategy: embed the generated taste bio
        prompt = build_taste_prompt(profile.favorite_genres, movies)
        if not prompt:
            prompt = ""
        taste_bio = generate_taste_bio(prompt, openai_client)
        taste_embedding = embed_taste_bio(taste_bio, openai_client)
        profile.taste_bio = taste_bio
        profile.taste_embedding = taste_embedding
        # Still compute negative for LLM strategy
        _, negative_emb = compute_taste_embeddings(user_id, db)
        profile.negative_embedding = negative_emb

    db.commit()
    db.refresh(profile)

    logger.info(
        "Rebuilt taste profile for user %s (strategy=%s)", user_id, EMBEDDING_STRATEGY
    )
    return profile


# --- Hidden movies CRUD ---


def hide_movie(user_id: str, tmdb_id: int, db: Session) -> HiddenMovie:
    """Hide a movie from recommendations."""
    existing = (
        db.query(HiddenMovie)
        .filter(HiddenMovie.user_id == user_id, HiddenMovie.tmdb_id == tmdb_id)
        .first()
    )
    if existing:
        return existing

    hidden = HiddenMovie(user_id=user_id, tmdb_id=tmdb_id)
    db.add(hidden)
    db.commit()
    db.refresh(hidden)
    return hidden


def unhide_movie(user_id: str, tmdb_id: int, db: Session) -> bool:
    """Unhide a movie. Returns True if found and deleted."""
    deleted = (
        db.query(HiddenMovie)
        .filter(HiddenMovie.user_id == user_id, HiddenMovie.tmdb_id == tmdb_id)
        .delete()
    )
    db.commit()
    return deleted > 0


def get_hidden_movies(
    user_id: str, db: Session, limit: int = 50, offset: int = 0
) -> dict:
    """Get user's hidden movies with movie details."""
    query = (
        db.query(HiddenMovie, Movie)
        .join(Movie, HiddenMovie.tmdb_id == Movie.tmdb_id)
        .filter(HiddenMovie.user_id == user_id)
        .order_by(HiddenMovie.created_at.desc())
    )
    total = db.query(HiddenMovie).filter(HiddenMovie.user_id == user_id).count()
    rows = query.offset(offset).limit(limit).all()

    results = []
    for hidden, movie in rows:
        results.append(
            {
                "tmdb_id": movie.tmdb_id,
                "title": movie.title,
                "year": movie.year,
                "poster_path": movie.poster_path,
                "hidden_at": hidden.created_at.isoformat(),
            }
        )
    return {"results": results, "total": total}


def get_hidden_movie_ids(user_id: str, db: Session) -> list[int]:
    """Get list of hidden tmdb_ids for a user."""
    return [
        row[0]
        for row in db.query(HiddenMovie.tmdb_id)
        .filter(HiddenMovie.user_id == user_id)
        .all()
    ]


def compute_genre_watch_counts(user_id: str, db: Session) -> tuple[dict[str, int], int]:
    """Count how many watched movies contain each genre for a user.

    Returns (genre_counts, total_movies_watched).
    """
    rows = (
        db.query(Movie.genres)
        .join(WatchedMovie, WatchedMovie.tmdb_id == Movie.tmdb_id)
        .filter(WatchedMovie.user_id == user_id)
        .all()
    )
    genre_counts: dict[str, int] = {}
    total = len(rows)
    for (genres,) in rows:
        for g in genres or []:
            name = g.get("name", "").lower()
            if name:
                genre_counts[name] = genre_counts.get(name, 0) + 1
    return genre_counts, total
