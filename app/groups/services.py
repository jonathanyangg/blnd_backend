import logging

import numpy as np
from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.groups.models import Group, GroupMember
from app.import_data.models import MovieEmbedding
from app.movies.models import Movie
from app.recommendations.ranking import rerank_candidates
from app.tracking.models import Watchlist, WatchedMovie

logger = logging.getLogger(__name__)

MAX_GROUP_MEMBERS = 10


def create_group(user_id: str, name: str, db: Session) -> dict:
    """Create a group with a linked watchlist and add creator as first member."""
    watchlist = Watchlist()
    db.add(watchlist)
    db.flush()

    group = Group(name=name, created_by=user_id, watchlist_id=watchlist.id)
    db.add(group)
    db.flush()

    member = GroupMember(group_id=group.id, user_id=user_id)
    db.add(member)
    db.commit()
    db.refresh(group)

    return _group_detail(group, db)


def list_groups(user_id: str, db: Session) -> dict:
    """List groups where the user is a member, with member counts."""
    group_ids = [
        row[0]
        for row in db.query(GroupMember.group_id)
        .filter(GroupMember.user_id == user_id)
        .all()
    ]
    if not group_ids:
        return {"groups": []}

    groups = db.query(Group).filter(Group.id.in_(group_ids)).all()

    results = []
    for g in groups:
        count = (
            db.query(func.count(GroupMember.user_id))
            .filter(GroupMember.group_id == g.id)
            .scalar()
        )
        results.append(
            {
                "id": g.id,
                "name": g.name,
                "created_by": str(g.created_by),
                "member_count": count or 0,
                "created_at": g.created_at,
            }
        )

    return {"groups": results}


def get_group(group_id: int, user_id: str, db: Session) -> dict:
    """Get group detail, verifying membership."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )

    _verify_membership(group_id, user_id, db)
    return _group_detail(group, db)


def add_member(group_id: int, user_id: str, username: str, db: Session) -> dict:
    """Add a member by username. Caller must be a member."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )

    _verify_membership(group_id, user_id, db)

    target = db.query(Profile).filter(Profile.username == username).first()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    existing = (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id, GroupMember.user_id == target.id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member",
        )

    count = (
        db.query(func.count(GroupMember.user_id))
        .filter(GroupMember.group_id == group_id)
        .scalar()
    )
    if (count or 0) >= MAX_GROUP_MEMBERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Group cannot exceed {MAX_GROUP_MEMBERS} members",
        )

    member = GroupMember(group_id=group_id, user_id=target.id)
    db.add(member)
    db.commit()

    return _group_detail(group, db)


def kick_member(group_id: int, user_id: str, target_user_id: str, db: Session) -> None:
    """Kick a member. Anyone can kick anyone except the owner."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )

    _verify_membership(group_id, user_id, db)

    if target_user_id == str(group.created_by):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot kick the group owner",
        )

    target_member = (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id, GroupMember.user_id == target_user_id)
        .first()
    )
    if not target_member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )

    db.delete(target_member)
    db.commit()

    _maybe_cleanup_group(group, db)


def leave_group(group_id: int, user_id: str, db: Session) -> None:
    """Leave a group. If owner leaves, transfer ownership."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )

    member = (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        .first()
    )
    if not member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a member of this group",
        )

    db.delete(member)
    db.flush()

    # Transfer ownership if the leaver is the owner
    if str(group.created_by) == user_id:
        earliest = (
            db.query(GroupMember)
            .filter(GroupMember.group_id == group_id)
            .order_by(GroupMember.joined_at.asc())
            .first()
        )
        if earliest:
            group.created_by = earliest.user_id
            db.flush()

    db.commit()
    _maybe_cleanup_group(group, db)


def delete_group(group_id: int, user_id: str, db: Session) -> None:
    """Delete a group. Creator only."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )

    if str(group.created_by) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the group creator can delete the group",
        )

    # Delete members
    db.query(GroupMember).filter(GroupMember.group_id == group_id).delete()

    # Delete watchlist (cascade deletes watchlist_movies)
    if group.watchlist_id:
        db.query(Watchlist).filter(Watchlist.id == group.watchlist_id).delete()

    db.delete(group)
    db.commit()


CANDIDATE_POOL_SIZE = 200


def get_group_recommendations(
    group_id: int,
    user_id: str,
    db: Session,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Generate group recommendations by averaging member taste embeddings + re-ranking."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )

    _verify_membership(group_id, user_id, db)

    # Get member IDs
    members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    member_ids = [str(m.user_id) for m in members]

    if not member_ids:
        return {"results": []}

    # Per member: top N rated movie embeddings, weighted average
    per_member_limit = max(5, 50 // len(member_ids))
    member_embeddings = []

    for mid in member_ids:
        rows = (
            db.query(WatchedMovie.rating, MovieEmbedding.embedding)
            .join(MovieEmbedding, WatchedMovie.tmdb_id == MovieEmbedding.tmdb_id)
            .filter(WatchedMovie.user_id == mid, WatchedMovie.rating.isnot(None))
            .order_by(WatchedMovie.rating.desc())
            .limit(per_member_limit)
            .all()
        )
        if not rows:
            continue

        ratings = np.array([float(r) for r, _ in rows])
        embeddings = np.array([e for _, e in rows])

        if ratings.sum() == 0:
            continue

        weighted_avg = np.average(embeddings, axis=0, weights=ratings)
        member_embeddings.append(weighted_avg)

    if not member_embeddings:
        return {"results": []}

    # Average all member embeddings together
    group_embedding = np.mean(member_embeddings, axis=0)

    # Union of all members' watched tmdb_ids for exclusion
    watched_ids = [
        row[0]
        for row in db.query(WatchedMovie.tmdb_id)
        .filter(WatchedMovie.user_id.in_(member_ids))
        .all()
    ]

    # Over-fetch candidates from pgvector
    embedding_str = "[" + ",".join(str(v) for v in group_embedding) + "]"

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
        return {"results": []}

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

    # Build group signal context: union of all members' genres, directors, cast
    all_genres: list[str] = []
    all_directors: set[str] = set()
    all_cast: set[str] = set()
    for mid in member_ids:
        profile = db.query(Profile).filter(Profile.id == mid).first()
        if profile and profile.favorite_genres:
            all_genres.extend(profile.favorite_genres)
        # Top 10 rated movies per member for director/cast
        top_movies = (
            db.query(Movie)
            .join(WatchedMovie, WatchedMovie.tmdb_id == Movie.tmdb_id)
            .filter(WatchedMovie.user_id == mid, WatchedMovie.rating.isnot(None))
            .order_by(WatchedMovie.rating.desc())
            .limit(10)
            .all()
        )
        for m in top_movies:
            if m.director:
                all_directors.add(m.director.lower())
            for c in (m.cast or [])[:5]:
                name = c.get("name", "")
                if name:
                    all_cast.add(name.lower())

    # Deduplicate genres
    unique_genres = list(set(all_genres))

    ranked = rerank_candidates(candidates, unique_genres, all_directors, all_cast)

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

    return {"results": results}


# --- Helpers ---


def _verify_membership(group_id: int, user_id: str, db: Session) -> None:
    """Raise 403 if user is not a member of the group."""
    member = (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        .first()
    )
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this group",
        )


def _group_detail(group: Group, db: Session) -> dict:
    """Build GroupDetailResponse dict."""
    members_rows = (
        db.query(GroupMember, Profile)
        .join(Profile, GroupMember.user_id == Profile.id)
        .filter(GroupMember.group_id == group.id)
        .all()
    )
    members = [
        {
            "id": str(p.id),
            "username": p.username,
            "display_name": p.display_name,
        }
        for _, p in members_rows
    ]
    return {
        "id": group.id,
        "name": group.name,
        "created_by": str(group.created_by),
        "members": members,
        "created_at": group.created_at,
    }


def _maybe_cleanup_group(group: Group, db: Session) -> None:
    """Delete group + watchlist if only 0 members remain."""
    count = (
        db.query(func.count(GroupMember.user_id))
        .filter(GroupMember.group_id == group.id)
        .scalar()
    )
    if (count or 0) == 0:
        if group.watchlist_id:
            db.query(Watchlist).filter(Watchlist.id == group.watchlist_id).delete()
        db.delete(group)
        db.commit()
