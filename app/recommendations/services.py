import logging
from datetime import datetime, timezone

import numpy as np
from openai import OpenAI
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.import_data.models import MovieEmbedding
from app.movies.models import Movie
from app.recommendations.models import HiddenMovie, MovieInteraction
from app.tracking.models import WatchedMovie, WatchlistMovie

logger = logging.getLogger(__name__)

AUTO_REBUILD_THRESHOLD = 50
REBUILD_ACTION_INTERVAL = 5
NEGATIVE_RATING_MIN_MOVIES = 10
NEGATIVE_RATING_PERCENTILE = 20
MAX_RATING = 5.0
WATCHLIST_WEIGHT = 1.5
# `interested` uses the watchlist weight. It is not a watchlist row.
# See docs/swipe-signals.md.
INTERESTED_WEIGHT = WATCHLIST_WEIGHT
# not_for_me is a weak negative. Hide stays the hard dislike at weight 1.0;
# a bad rating weighs up to (MAX_RATING - rating) = 4.5.
NOT_FOR_ME_WEIGHT = 0.5


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


def increment_action_counter(user_id: str, db: Session) -> bool:
    """Increment action counter. Returns True if a rebuild should be triggered."""
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        return False

    profile.actions_since_rebuild = (profile.actions_since_rebuild or 0) + 1

    if profile.actions_since_rebuild >= REBUILD_ACTION_INTERVAL:
        profile.actions_since_rebuild = 0
        db.commit()
        logger.info("Debounced taste rebuild triggered for user %s", user_id)
        return True

    db.commit()
    return False


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
    user_id: str, db: Session, profile: Profile | None = None
) -> tuple[list[str], set[str], set[str]]:
    """Extract user's favorite genres, top directors, and top cast from their top-rated movies.

    Returns (favorite_genres, top_directors_lowered, top_cast_lowered).
    """
    if profile is None:
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

    # Merge liked actors into cast signal
    from app.actors.services import get_liked_actor_names

    top_cast |= get_liked_actor_names(user_id, db)

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
    user_id: str, db: Session, profile: Profile | None = None
) -> tuple[list[float] | None, list[float] | None, float | None]:
    """Compute taste embeddings using rating-weighted average.

    Positive embedding: weighted average of movies at or above the user's 20th
    percentile rating, weight = rating value (0.5–5.0). Watchlist movies add
    WATCHLIST_WEIGHT each. `interested` swipes add INTERESTED_WEIGHT each and
    are not watchlist rows. A rating on the same movie wins; the swipe is skipped.

    Negative embedding from ratings: if user has 10+ rated movies, movies below
    the 20th percentile contribute to the negative embedding, weighted by
    (MAX_RATING - rating) so lower ratings push harder. Hidden movies add weight
    1.0 (hard dislike). `not_for_me` swipes add NOT_FOR_ME_WEIGHT and are not
    hides. A rating or a hide on the same movie wins.

    If user has <10 rated movies, no rating-derived negatives (sample too small).

    Returns (positive_embedding, negative_embedding, sum_weights). sum_weights is
    the denominator of the weighted average (Σ positive weights) — needed by
    match-score leave-one-out. None when the positive vector is a genre seed.
    """
    rows = (
        db.query(WatchedMovie.tmdb_id, WatchedMovie.rating, MovieEmbedding.embedding)
        .join(MovieEmbedding, WatchedMovie.tmdb_id == MovieEmbedding.tmdb_id)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.rating.isnot(None))
        .all()
    )
    interested_rows = _swipe_embeddings(user_id, "interested", db)
    not_for_me_rows = _swipe_embeddings(user_id, "not_for_me", db)
    # Watchlist-only users still take the genre-seed path. Swipes are enough
    # on their own to build a vector.
    if not rows and not interested_rows and not not_for_me_rows:
        return None, None, None

    positive_emb: np.ndarray | None = None
    sum_weights = 0.0
    pos_rated_ids: set[int] = set()
    neg_rated_ids: set[int] = set()
    neg_parts: list[np.ndarray] = []
    neg_weights: list[np.ndarray] = []

    if rows:
        ratings = np.array([float(r) for _, r, _ in rows])
        embeddings = np.array([e for _, _, e in rows])

        # Split positive/negative based on 20th percentile (only with enough data)
        if len(rows) >= NEGATIVE_RATING_MIN_MOVIES:
            threshold = float(np.percentile(ratings, NEGATIVE_RATING_PERCENTILE))
            pos_mask = ratings >= threshold
            neg_mask = ~pos_mask
        else:
            pos_mask = np.ones(len(ratings), dtype=bool)
            neg_mask = np.zeros(len(ratings), dtype=bool)

        pos_embeddings = embeddings[pos_mask]
        pos_ratings = ratings[pos_mask]
        if len(pos_embeddings) > 0:
            positive_emb = np.average(pos_embeddings, axis=0, weights=pos_ratings)
            sum_weights = float(pos_ratings.sum())
            pos_rated_ids = {rows[i][0] for i in np.flatnonzero(pos_mask)}

        if neg_mask.any():
            neg_parts.append(embeddings[neg_mask])
            neg_weights.append(MAX_RATING - ratings[neg_mask])
            neg_rated_ids = {rows[i][0] for i in np.flatnonzero(neg_mask)}

    rated_ids = pos_rated_ids | neg_rated_ids
    # Hidden is the hard dislike. Load it before the positive blend so an
    # interested swipe on a hidden title does not pull taste both ways.
    hidden_rows = (
        db.query(HiddenMovie.tmdb_id, MovieEmbedding.embedding)
        .join(MovieEmbedding, HiddenMovie.tmdb_id == MovieEmbedding.tmdb_id)
        .filter(HiddenMovie.user_id == user_id)
        .all()
    )
    hidden_ids = {tid for tid, _ in hidden_rows}
    interested_ids = {
        tid
        for tid, _ in interested_rows
        if tid not in rated_ids and tid not in hidden_ids
    }

    # Watchlist blend. Same merge as before when there is no interested swipe.
    # An interested swipe on a watchlisted movie replaces the watchlist weight.
    if profile is None:
        profile = db.query(Profile).filter(Profile.id == user_id).first()
    if rows and profile and profile.watchlist_id and positive_emb is not None:
        wl_query = (
            db.query(MovieEmbedding.embedding)
            .join(WatchlistMovie, WatchlistMovie.tmdb_id == MovieEmbedding.tmdb_id)
            .filter(WatchlistMovie.watchlist_id == profile.watchlist_id)
        )
        if interested_ids:
            wl_query = wl_query.filter(WatchlistMovie.tmdb_id.notin_(interested_ids))
        wl_rows = wl_query.all()
        if wl_rows:
            positive_emb, sum_weights = _merge_positive(
                positive_emb,
                sum_weights,
                np.array([e for (e,) in wl_rows]),
                WATCHLIST_WEIGHT,
            )

    interested_embs = [e for tid, e in interested_rows if tid in interested_ids]
    if interested_embs:
        positive_emb, sum_weights = _merge_positive(
            positive_emb,
            sum_weights,
            np.array(interested_embs),
            INTERESTED_WEIGHT,
        )

    # Hidden movies: uniform weight 1.0. This is the hard dislike, not a swipe.
    if hidden_rows:
        neg_parts.append(np.array([e for _, e in hidden_rows]))
        neg_weights.append(np.ones(len(hidden_rows)))

    not_for_me_embs = [
        e
        for tid, e in not_for_me_rows
        if tid not in rated_ids and tid not in hidden_ids
    ]
    if not_for_me_embs:
        neg_parts.append(np.array(not_for_me_embs))
        neg_weights.append(np.full(len(not_for_me_embs), NOT_FOR_ME_WEIGHT))

    negative_emb = None
    if neg_parts:
        all_neg_emb = np.concatenate(neg_parts, axis=0)
        all_neg_w = np.concatenate(neg_weights)
        negative_emb = np.average(all_neg_emb, axis=0, weights=all_neg_w).tolist()

    if positive_emb is None:
        return None, negative_emb, None
    return positive_emb.tolist(), negative_emb, sum_weights


def _swipe_embeddings(
    user_id: str, interaction_type: str, db: Session
) -> list[tuple[int, list[float]]]:
    """Embeddings for one swipe type. Movies without an embedding are skipped."""
    return (
        db.query(MovieInteraction.tmdb_id, MovieEmbedding.embedding)
        .join(MovieEmbedding, MovieInteraction.tmdb_id == MovieEmbedding.tmdb_id)
        .filter(
            MovieInteraction.user_id == user_id,
            MovieInteraction.interaction_type == interaction_type,
        )
        .all()
    )


def _merge_positive(
    positive_emb: np.ndarray | None,
    sum_weights: float,
    embeddings: np.ndarray,
    each_weight: float,
) -> tuple[np.ndarray, float]:
    """Fold a block of equal-weight movies into the positive taste vector."""
    extra = len(embeddings) * each_weight
    average = np.mean(embeddings, axis=0)
    if positive_emb is None or sum_weights <= 0:
        return average, extra
    total = sum_weights + extra
    merged = (positive_emb * sum_weights + average * extra) / total
    return merged, total


GENRE_SEED_TOP_N = 20
GENRE_SEED_MIN_VOTE = 7.0
GLOBAL_SEED_TOP_N = 100

# Maps iOS-facing genre names to canonical TMDB genre names.
# TMDB stores genres in movies.genres JSONB as [{"id": ..., "name": "..."}].
IOS_TO_TMDB_GENRE = {
    "action": "Action",
    "comedy": "Comedy",
    "horror": "Horror",
    "sci-fi": "Science Fiction",
    "romance": "Romance",
    "thriller": "Thriller",
    "drama": "Drama",
    "animation": "Animation",
    "documentary": "Documentary",
    "mystery": "Mystery",
    "fantasy": "Fantasy",
    "crime": "Crime",
}


def compute_genre_seed_embedding(
    favorite_genres: list[str] | None, db: Session
) -> list[float] | None:
    """Build a fallback taste embedding from genre preferences alone.

    For each favorite genre, averages the embeddings of the top ~20 movies in
    that genre (vote_average >= 7.0), weighted by vote_average. If no genres,
    falls back to the global top 100 highest-rated movies.

    Used as a cold-start seed for users who complete onboarding without rating
    any movies. Replaced on the next rebuild if the user rates something.
    """
    all_embeddings: list[np.ndarray] = []
    all_weights: list[float] = []

    if favorite_genres:
        for genre_name in favorite_genres:
            tmdb_name = IOS_TO_TMDB_GENRE.get(genre_name.lower(), genre_name)
            rows = (
                db.query(Movie.vote_average, MovieEmbedding.embedding)
                .join(MovieEmbedding, Movie.tmdb_id == MovieEmbedding.tmdb_id)
                .filter(
                    Movie.vote_average >= GENRE_SEED_MIN_VOTE,
                    Movie.genres.contains([{"name": tmdb_name}]),
                )
                .order_by(Movie.vote_average.desc())
                .limit(GENRE_SEED_TOP_N)
                .all()
            )
            for vote_avg, emb in rows:
                all_embeddings.append(np.array(emb))
                all_weights.append(float(vote_avg or GENRE_SEED_MIN_VOTE))
    else:
        # No genres — fall back to global top N by vote_average
        rows = (
            db.query(Movie.vote_average, MovieEmbedding.embedding)
            .join(MovieEmbedding, Movie.tmdb_id == MovieEmbedding.tmdb_id)
            .filter(Movie.vote_average.isnot(None))
            .order_by(Movie.vote_average.desc())
            .limit(GLOBAL_SEED_TOP_N)
            .all()
        )
        for vote_avg, emb in rows:
            all_embeddings.append(np.array(emb))
            all_weights.append(float(vote_avg or 7.0))

    if not all_embeddings:
        return None

    emb_array = np.stack(all_embeddings, axis=0)
    weights = np.array(all_weights)
    return np.average(emb_array, axis=0, weights=weights).tolist()


def rebuild_taste_profile(
    user_id: str, db: Session, openai_client: OpenAI
) -> Profile | None:
    """Orchestrator: build taste embedding + generate taste bio for display.

    Tries rated-movie weighted average first. Falls back to genre seed
    embedding (or global top-rated average) if the user has no ratings yet.
    """
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        return None

    movies = get_top_rated_movies(user_id, db)

    # Taste embedding: switch between strategies
    if EMBEDDING_STRATEGY == "average":
        positive_emb, negative_emb, sum_weights = compute_taste_embeddings(
            user_id, db, profile=profile
        )
        if not positive_emb:
            # Cold-start fallback: seed from favorite genres (or global top)
            seed = compute_genre_seed_embedding(profile.favorite_genres, db)
            if not seed:
                return profile  # No movies embedded yet, nothing to seed from
            profile.taste_embedding = seed
            # Keep a swipe-only negative (not_for_me). None when there is none,
            # which is the same as the old cold-start path.
            profile.negative_embedding = negative_emb
            profile.taste_sum_weights = None
            db.commit()
            db.refresh(profile)
            logger.info(
                "Seeded taste profile from %s for user %s",
                "genres" if profile.favorite_genres else "global",
                user_id,
            )
            return profile
        profile.taste_embedding = positive_emb
        profile.negative_embedding = negative_emb
        profile.taste_sum_weights = sum_weights
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
        _, negative_emb, _ = compute_taste_embeddings(user_id, db, profile=profile)
        profile.negative_embedding = negative_emb
        # LLM-strategy taste embedding is not a weighted sum of movies, so
        # leave-one-out doesn't apply — clear sum_weights.
        profile.taste_sum_weights = None

    db.commit()
    db.refresh(profile)

    logger.info(
        "Rebuilt taste profile for user %s (strategy=%s)", user_id, EMBEDDING_STRATEGY
    )
    return profile


# --- Swipe signals ---


def record_interaction(
    user_id: str, tmdb_id: int, interaction_type: str, db: Session
) -> MovieInteraction:
    """Store one swipe per user and movie. A new swipe replaces the old one.

    Does not write watchlist_movies or hidden_movies.
    """
    existing = (
        db.query(MovieInteraction)
        .filter(
            MovieInteraction.user_id == user_id,
            MovieInteraction.tmdb_id == tmdb_id,
        )
        .first()
    )
    if existing:
        if existing.interaction_type != interaction_type:
            existing.interaction_type = interaction_type
            existing.created_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing)
        return existing

    row = MovieInteraction(
        user_id=user_id, tmdb_id=tmdb_id, interaction_type=interaction_type
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_interaction(
    user_id: str, tmdb_id: int, interaction_type: str, db: Session
) -> bool:
    """Remove one swipe type. Returns False when that signal was not stored."""
    deleted = (
        db.query(MovieInteraction)
        .filter(
            MovieInteraction.user_id == user_id,
            MovieInteraction.tmdb_id == tmdb_id,
            MovieInteraction.interaction_type == interaction_type,
        )
        .delete()
    )
    db.commit()
    return deleted > 0


def get_swiped_movie_ids(user_id: str, db: Session) -> list[int]:
    """Titles this user has swiped. Used to drop them from the personal deck."""
    return [
        row[0]
        for row in db.query(MovieInteraction.tmdb_id)
        .filter(MovieInteraction.user_id == user_id)
        .all()
    ]


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
