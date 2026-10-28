"""Save onboarding film picks and rebuild the caller's taste embedding."""

import numpy as np
from openai import OpenAI
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.import_data.models import MovieEmbedding
from app.movies.services import get_movie_details
from app.onboarding.schemas import OnboardingTasteRequest, TastePick
from app.recommendations.pipeline import run_recommendation_pipeline
from app.recommendations.services import rebuild_taste_profile
from app.recommendations.views import _build_user_context
from app.tracking.models import WatchedMovie

# A pick with no rating is still a positive signal, weighted like a 4-star.
_UNRATED_WEIGHT = 4.0


async def seed_onboarding_taste(
    user_id: str,
    body: OnboardingTasteRequest,
    db: Session,
    tmdb_client,
    openai_client: OpenAI,
) -> dict | None:
    """Store picks, rebuild taste, and return recommendations.

    Returns None when the user has no profile yet.
    """
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if profile is None:
        return None

    saved: list[dict] = []
    for pick in body.picks:
        await get_movie_details(pick.tmdb_id, db, tmdb_client)
        values = {
            "user_id": user_id,
            "tmdb_id": pick.tmdb_id,
            "rating": pick.rating,
            "source": "onboarding_taste",
        }
        statement = pg_insert(WatchedMovie).values(**values)
        if pick.rating is None:
            statement = statement.on_conflict_do_nothing(
                index_elements=["user_id", "tmdb_id"]
            )
        else:
            statement = statement.on_conflict_do_update(
                index_elements=["user_id", "tmdb_id"],
                set_={"rating": pick.rating},
            )
        db.execute(statement)
        stored = (
            db.query(WatchedMovie.rating)
            .filter(
                WatchedMovie.user_id == user_id,
                WatchedMovie.tmdb_id == pick.tmdb_id,
            )
            .scalar()
        )
        saved.append({"tmdb_id": pick.tmdb_id, "rating": stored})
    db.commit()

    profile = rebuild_taste_profile(user_id, db, openai_client)
    if profile is None:
        return None
    _blend_unrated_picks(profile, body.picks, db)

    if profile.taste_embedding is None:
        results: list[dict] = []
    else:
        context = _build_user_context(user_id, profile, db)
        results = run_recommendation_pipeline(context, db, limit=20, offset=0)

    return {
        "saved": saved,
        "results": results,
        "taste_bio": profile.taste_bio,
    }


def _blend_unrated_picks(
    profile: Profile, picks: list[TastePick], db: Session
) -> None:
    """Fold unrated picks into the taste embedding.

    Rated picks are already in the rating-weighted average. Unrated picks are
    not, so they are mixed in at a fixed positive weight. When the user rated
    nothing, the pick average replaces the genre-seed fallback.
    """
    unrated_ids = [pick.tmdb_id for pick in picks if pick.rating is None]
    if not unrated_ids:
        return
    rows = (
        db.query(MovieEmbedding.embedding)
        .filter(MovieEmbedding.tmdb_id.in_(unrated_ids))
        .all()
    )
    if not rows:
        return

    extra = np.mean([np.array(embedding, dtype=float) for (embedding,) in rows], axis=0)
    extra_weight = _UNRATED_WEIGHT * len(rows)
    has_rated_pick = any(pick.rating is not None for pick in picks)
    if profile.taste_embedding is None or (
        profile.taste_sum_weights is None and not has_rated_pick
    ):
        profile.taste_embedding = extra.tolist()
        profile.taste_sum_weights = extra_weight
    else:
        current_weight = float(profile.taste_sum_weights or extra_weight)
        current = np.array(list(profile.taste_embedding), dtype=float)
        total = current_weight + extra_weight
        profile.taste_embedding = (
            (current * current_weight + extra * extra_weight) / total
        ).tolist()
        profile.taste_sum_weights = total
    db.commit()
    db.refresh(profile)
