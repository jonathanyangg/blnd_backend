from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.auth.models import Profile
from app.core.rate_limit import LIMIT_DEFAULT, LIMIT_REFRESH, limiter
from app.dependencies import get_current_user, get_db, openai_client
from app.recommendations import schemas, services
from app.recommendations.pipeline import (
    RecommendationContext,
    run_recommendation_pipeline,
)
from app.tracking.models import WatchedMovie

router = APIRouter()


def _build_user_context(
    user_id: str, profile: Profile, db: Session
) -> RecommendationContext:
    """Build a RecommendationContext for a single user."""
    watched_ids = [
        row[0]
        for row in db.query(WatchedMovie.tmdb_id)
        .filter(WatchedMovie.user_id == user_id)
        .all()
    ]
    hidden_ids = services.get_hidden_movie_ids(user_id, db)
    exclude_ids = list(set(watched_ids + hidden_ids))

    user_genres, top_directors, top_cast = services.get_user_signal_context(user_id, db)
    genre_counts, total_watches = services.compute_genre_watch_counts(user_id, db)

    return RecommendationContext(
        positive_embedding=list(profile.taste_embedding),
        negative_embedding=list(profile.negative_embedding)
        if profile.negative_embedding is not None
        else None,
        exclude_ids=exclude_ids,
        user_genres=user_genres,
        top_directors=top_directors,
        top_cast=top_cast,
        genre_watch_counts=genre_counts,
        total_watches=total_watches,
    )


@router.get("/me", response_model=schemas.RecommendationsResponse)
@limiter.limit(LIMIT_DEFAULT)
def get_recommendations(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        return {"results": [], "taste_bio": None}

    # Build taste profile inline if missing
    if profile.taste_embedding is None:
        profile = services.rebuild_taste_profile(user_id, db, openai_client)
        if not profile or profile.taste_embedding is None:
            return {"results": [], "taste_bio": profile.taste_bio if profile else None}

    ctx = _build_user_context(user_id, profile, db)
    results = run_recommendation_pipeline(ctx, db, limit, offset)
    return {"results": results, "taste_bio": profile.taste_bio}


@router.post("/me/refresh", response_model=schemas.RecommendationsResponse)
@limiter.limit(LIMIT_REFRESH)
def refresh_recommendations(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=50),
):
    # Force rebuild taste profile synchronously, then return fresh recs
    profile = services.rebuild_taste_profile(user_id, db, openai_client)
    if not profile or profile.taste_embedding is None:
        return {"results": [], "taste_bio": profile.taste_bio if profile else None}

    ctx = _build_user_context(user_id, profile, db)
    results = run_recommendation_pipeline(ctx, db, limit, 0)
    return {"results": results, "taste_bio": profile.taste_bio}


# --- Hidden Movies ---


@router.post("/{tmdb_id}/hide", response_model=schemas.HiddenMovieResponse)
@limiter.limit(LIMIT_DEFAULT)
def hide_movie(
    request: Request,
    tmdb_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hidden = services.hide_movie(user_id, tmdb_id, db)

    # Auto-rebuild if <50 rated movies
    if services.should_auto_rebuild(user_id, db):
        try:
            services.rebuild_taste_profile(user_id, db, openai_client)
        except Exception:
            pass  # Non-critical

    # Fetch movie details for response
    from app.movies.models import Movie

    movie = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
    return {
        "tmdb_id": tmdb_id,
        "title": movie.title if movie else "Unknown",
        "year": movie.year if movie else None,
        "poster_path": movie.poster_path if movie else None,
        "hidden_at": hidden.created_at.isoformat(),
    }


@router.delete("/{tmdb_id}/hide", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
def unhide_movie(
    request: Request,
    tmdb_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deleted = services.unhide_movie(user_id, tmdb_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Movie not hidden")


@router.get("/hidden", response_model=schemas.HiddenMoviesListResponse)
@limiter.limit(LIMIT_DEFAULT)
def list_hidden_movies(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return services.get_hidden_movies(user_id, db, limit, offset)
