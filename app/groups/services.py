from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np
from fastapi import HTTPException, status
from sqlalchemy import func, select, union_all
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.groups.schemas import UpdateGroupRequest

from app.auth.models import Profile
from app.groups.models import Group, GroupMember
from app.import_data.models import MovieEmbedding
from app.movies.models import Movie
from app.recommendations.models import HiddenMovie
from app.recommendations.pipeline import (
    RecommendationContext,
    run_recommendation_pipeline,
)
from app.subscriptions.services import is_premium
from app.tracking.models import Watchlist, WatchedMovie, WatchlistMovie

logger = logging.getLogger(__name__)

FREE_GROUP_CAP = 4
PREMIUM_GROUP_CAP = 12


def _group_cap(group_id: int, db: Session) -> int:
    """Group tier is the max of any member's tier -- one premium member
    unlocks the premium cap for the whole group."""
    has_premium = (
        db.query(Profile)
        .join(GroupMember, GroupMember.user_id == Profile.id)
        .filter(GroupMember.group_id == group_id)
        .filter(Profile.subscription_tier == "premium")
        .limit(1)
        .first()
    )
    if has_premium and is_premium(has_premium):
        return PREMIUM_GROUP_CAP
    return FREE_GROUP_CAP


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

    # Batch fetch all members for all groups in one query (avoids N+1)
    all_members = (
        db.query(GroupMember, Profile)
        .join(Profile, GroupMember.user_id == Profile.id)
        .filter(GroupMember.group_id.in_(group_ids))
        .all()
    )
    members_by_group: dict[int, list[Profile]] = defaultdict(list)
    for gm, profile in all_members:
        members_by_group[gm.group_id].append(profile)

    results = []
    for g in groups:
        group_members = members_by_group.get(g.id, [])
        avatars = [p.avatar_url for p in group_members[:4]]
        results.append(
            {
                "id": g.id,
                "name": g.name,
                "created_by": str(g.created_by),
                "member_count": len(group_members),
                "member_avatars": avatars,
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


def update_group(
    group_id: int, user_id: str, updates: UpdateGroupRequest, db: Session
) -> dict:
    """Update group fields. Any member can update."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )

    _verify_membership(group_id, user_id, db)

    fields = updates.model_dump(exclude_unset=True)
    if "name" in fields:
        group.name = fields["name"]

    db.commit()
    db.refresh(group)
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
    cap = _group_cap(group_id, db)
    if (count or 0) >= cap:
        if cap == FREE_GROUP_CAP:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "free_group_cap",
                    "cap": FREE_GROUP_CAP,
                    "premium_cap": PREMIUM_GROUP_CAP,
                    "message": (
                        f"Free groups are limited to {FREE_GROUP_CAP} members. "
                        f"Upgrade to blnd+ for groups up to {PREMIUM_GROUP_CAP}."
                    ),
                },
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "group_full",
                "cap": cap,
                "message": f"Group is full ({cap} members max).",
            },
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

    # Save watchlist_id before deleting the group
    watchlist_id = group.watchlist_id

    db.delete(group)
    db.flush()

    # Delete watchlist after group is gone (group had FK to watchlist)
    if watchlist_id:
        db.query(Watchlist).filter(Watchlist.id == watchlist_id).delete()

    db.commit()


def get_group_recommendations(
    group_id: int,
    user_id: str,
    db: Session,
    limit: int = 20,
    offset: int = 0,
    extra_exclude: list[int] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
) -> dict:
    """Generate group recommendations using the shared pipeline."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )

    _verify_membership(group_id, user_id, db)

    members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    member_ids = [str(m.user_id) for m in members]

    if not member_ids:
        return {"results": []}

    # Batch fetch all member profiles in one query
    profiles = db.query(Profile).filter(Profile.id.in_(member_ids)).all()
    profile_map = {str(p.id): p for p in profiles}

    # Build averaged positive + negative embeddings from cached profiles
    pos_embeddings = []
    neg_embeddings = []
    for mid in member_ids:
        profile = profile_map.get(mid)
        if profile and profile.taste_embedding is not None:
            pos_embeddings.append(np.array(list(profile.taste_embedding)))
            if profile.negative_embedding is not None:
                neg_embeddings.append(np.array(list(profile.negative_embedding)))

    if not pos_embeddings:
        # Fallback: build from rated movies directly (single batch query)
        per_member_limit = max(5, 50 // len(member_ids))
        all_rows = (
            db.query(
                WatchedMovie.user_id, WatchedMovie.rating, MovieEmbedding.embedding
            )
            .join(MovieEmbedding, WatchedMovie.tmdb_id == MovieEmbedding.tmdb_id)
            .filter(
                WatchedMovie.user_id.in_(member_ids),
                WatchedMovie.rating.isnot(None),
            )
            .order_by(WatchedMovie.user_id, WatchedMovie.rating.desc())
            .all()
        )
        rows_by_member: dict[str, list[tuple[float, list[float]]]] = defaultdict(list)
        for uid, rating, embedding in all_rows:
            uid_str = str(uid)
            if len(rows_by_member[uid_str]) < per_member_limit:
                rows_by_member[uid_str].append((float(rating), embedding))
        for mid in member_ids:
            rows = rows_by_member.get(mid, [])
            if not rows:
                continue
            ratings = np.array([r for r, _ in rows])
            embeddings = np.array([e for _, e in rows])
            if ratings.sum() == 0:
                continue
            weighted_avg = np.average(embeddings, axis=0, weights=ratings)
            pos_embeddings.append(weighted_avg)

    if not pos_embeddings:
        return {"results": []}

    group_positive = np.mean(pos_embeddings, axis=0).tolist()
    group_negative = (
        np.mean(neg_embeddings, axis=0).tolist() if neg_embeddings else None
    )

    # Union of all members' watched + hidden + group watchlist IDs (single query)
    exclude_stmts = [
        select(WatchedMovie.tmdb_id).where(WatchedMovie.user_id.in_(member_ids)),
        select(HiddenMovie.tmdb_id).where(HiddenMovie.user_id.in_(member_ids)),
    ]
    if group.watchlist_id:
        exclude_stmts.append(
            select(WatchlistMovie.tmdb_id).where(
                WatchlistMovie.watchlist_id == group.watchlist_id
            )
        )
    combined = union_all(*exclude_stmts)
    exclude_ids = list(
        {row[0] for row in db.execute(combined).all()} | set(extra_exclude or [])
    )

    # Merge signal context from cached profiles + batch top movies query
    all_genres: list[str] = []
    all_directors: set[str] = set()
    all_cast: set[str] = set()
    for mid in member_ids:
        profile = profile_map.get(mid)
        if profile and profile.favorite_genres:
            all_genres.extend(profile.favorite_genres)

    # Single query: top 10 rated movies per member (union)
    top_movies = (
        db.query(Movie)
        .join(WatchedMovie, WatchedMovie.tmdb_id == Movie.tmdb_id)
        .filter(
            WatchedMovie.user_id.in_(member_ids),
            WatchedMovie.rating.isnot(None),
        )
        .order_by(WatchedMovie.rating.desc())
        .limit(10 * len(member_ids))
        .all()
    )
    for m in top_movies:
        if m.director:
            all_directors.add(m.director.lower())
        for c in (m.cast or [])[:5]:
            name = c.get("name", "")
            if name:
                all_cast.add(name.lower())
    unique_genres = list(set(all_genres))

    # Combined genre watch counts — single query across all members
    all_genre_rows = (
        db.query(Movie.genres)
        .join(WatchedMovie, WatchedMovie.tmdb_id == Movie.tmdb_id)
        .filter(WatchedMovie.user_id.in_(member_ids))
        .all()
    )
    combined_counts: dict[str, int] = {}
    combined_total = len(all_genre_rows)
    for (genres,) in all_genre_rows:
        for g in genres or []:
            name = g.get("name", "").lower()
            if name:
                combined_counts[name] = combined_counts.get(name, 0) + 1

    ctx = RecommendationContext(
        positive_embedding=group_positive,
        negative_embedding=group_negative,
        exclude_ids=exclude_ids,
        user_genres=unique_genres,
        top_directors=all_directors,
        top_cast=all_cast,
        genre_watch_counts=combined_counts,
        total_watches=combined_total,
        year_min=year_min,
        year_max=year_max,
        cf_user_ids=[str(mid) for mid in member_ids],
    )

    results = run_recommendation_pipeline(ctx, db, limit, offset)
    return {"results": results}


def compute_group_match_scores(
    group_id: int, tmdb_ids: list[int], db: Session
) -> dict[int, float]:
    """Compute group match scores for a list of tmdb_ids.

    Averages member taste embeddings and computes cosine similarity per movie.
    Returns {tmdb_id: score} where score is 0-1.
    """
    if not tmdb_ids:
        return {}

    members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    member_ids = [str(m.user_id) for m in members]

    if not member_ids:
        return {}

    # Build group embedding from members' rated movies (single batch query)
    per_member_limit = max(5, 50 // len(member_ids))
    all_rows = (
        db.query(WatchedMovie.user_id, WatchedMovie.rating, MovieEmbedding.embedding)
        .join(MovieEmbedding, WatchedMovie.tmdb_id == MovieEmbedding.tmdb_id)
        .filter(
            WatchedMovie.user_id.in_(member_ids),
            WatchedMovie.rating.isnot(None),
        )
        .order_by(WatchedMovie.user_id, WatchedMovie.rating.desc())
        .all()
    )

    # Group by member and take top N per member in memory
    rows_by_member: dict[str, list[tuple[float, list[float]]]] = defaultdict(list)
    for uid, rating, embedding in all_rows:
        uid_str = str(uid)
        if len(rows_by_member[uid_str]) < per_member_limit:
            rows_by_member[uid_str].append((float(rating), embedding))

    member_embeddings = []
    for mid in member_ids:
        rows = rows_by_member.get(mid, [])
        if not rows:
            continue

        ratings = np.array([r for r, _ in rows])
        embeddings = np.array([e for _, e in rows])
        if ratings.sum() == 0:
            continue
        weighted_avg = np.average(embeddings, axis=0, weights=ratings)
        member_embeddings.append(weighted_avg)

    if not member_embeddings:
        return {}

    group_embedding = np.mean(member_embeddings, axis=0)
    group_norm = np.linalg.norm(group_embedding)
    if group_norm == 0:
        return {}
    group_embedding = group_embedding / group_norm

    # Get embeddings for requested movies
    movie_embeds = (
        db.query(MovieEmbedding).filter(MovieEmbedding.tmdb_id.in_(tmdb_ids)).all()
    )

    scores = {}
    for me in movie_embeds:
        emb = np.array(me.embedding)
        norm = np.linalg.norm(emb)
        if norm == 0:
            continue
        similarity = float(np.dot(group_embedding, emb / norm))
        # Clamp to [0, 1] and convert to match percentage
        scores[me.tmdb_id] = max(0.0, min(1.0, (similarity + 1) / 2))

    return scores


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
            "avatar_url": p.avatar_url,
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
