from sqlalchemy.orm import Session

from app.actors.models import LikedActor


def like_actor(
    user_id: str,
    tmdb_person_id: int,
    name: str,
    profile_path: str | None,
    db: Session,
) -> LikedActor:
    """Like an actor. Returns existing if already liked."""
    existing = (
        db.query(LikedActor)
        .filter(
            LikedActor.user_id == user_id,
            LikedActor.tmdb_person_id == tmdb_person_id,
        )
        .first()
    )
    if existing:
        return existing

    liked = LikedActor(
        user_id=user_id,
        tmdb_person_id=tmdb_person_id,
        name=name,
        profile_path=profile_path,
    )
    db.add(liked)
    db.commit()
    db.refresh(liked)
    return liked


def unlike_actor(user_id: str, tmdb_person_id: int, db: Session) -> bool:
    """Unlike an actor. Returns True if found and deleted."""
    deleted = (
        db.query(LikedActor)
        .filter(
            LikedActor.user_id == user_id,
            LikedActor.tmdb_person_id == tmdb_person_id,
        )
        .delete()
    )
    db.commit()
    return deleted > 0


def get_liked_actors(
    user_id: str, db: Session, limit: int = 50, offset: int = 0
) -> dict:
    """Get user's liked actors, ordered by most recent."""
    query = (
        db.query(LikedActor)
        .filter(LikedActor.user_id == user_id)
        .order_by(LikedActor.created_at.desc())
    )
    total = db.query(LikedActor).filter(LikedActor.user_id == user_id).count()
    rows = query.offset(offset).limit(limit).all()

    results = []
    for actor in rows:
        results.append(
            {
                "tmdb_person_id": actor.tmdb_person_id,
                "name": actor.name,
                "profile_path": actor.profile_path,
                "liked_at": actor.created_at.isoformat(),
            }
        )
    return {"results": results, "total": total}


def get_liked_actor_names(user_id: str, db: Session) -> set[str]:
    """Get lowercased names of liked actors for recommendation integration."""
    return {
        row[0].lower()
        for row in db.query(LikedActor.name).filter(LikedActor.user_id == user_id).all()
    }


def is_actor_liked(user_id: str, tmdb_person_id: int, db: Session) -> bool:
    """Check if user has liked a specific actor."""
    return (
        db.query(LikedActor)
        .filter(
            LikedActor.user_id == user_id,
            LikedActor.tmdb_person_id == tmdb_person_id,
        )
        .first()
        is not None
    )
