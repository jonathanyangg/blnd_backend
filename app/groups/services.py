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
from app.auth.visibility import visible_user_ids
from app.groups.models import Group, GroupMember
from app.groups.names import blend_display_name, default_blend_name, first_name
from app.import_data.models import MovieEmbedding
from app.movies.models import Movie
from app.recommendations.models import HiddenMovie, MovieInteraction
from app.recommendations.pipeline import (
    RecommendationContext,
    run_recommendation_pipeline,
)
from app.recommendations.group_scoring import MemberTaste
from app.subscriptions.services import is_premium
from app.tracking.models import (
    InterestedMovie,
    Watchlist,
    WatchedMovie,
    WatchlistMovie,
)

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


def _people_display_name(stored_name: str | None, people: list[Profile]) -> str:
    return blend_display_name(
        stored_name, [first_name(p.display_name, p.username) for p in people]
    )


def group_display_name(group: Group, db: Session) -> str:
    """Name to show. Does not write the generated string into groups.name."""
    people = (
        db.query(Profile)
        .join(GroupMember, GroupMember.user_id == Profile.id)
        .filter(GroupMember.group_id == group.id)
        .order_by(GroupMember.joined_at, GroupMember.user_id)
        .all()
    )
    return _people_display_name(group.name, people)


def create_group(user_id: str, name: str | None, db: Session) -> dict:
    """Create a group with a linked watchlist and add creator as first member."""
    if name is not None:
        name = name.strip() or None
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
        .order_by(GroupMember.joined_at, GroupMember.user_id)
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
                "display_name": _people_display_name(g.name, group_members),
                "created_by": str(g.created_by),
                "member_count": len(group_members),
                "member_avatars": avatars,
                "created_at": g.created_at,
            }
        )

    return {"groups": results}


def search_groups(
    user_id: str, query: str, db: Session, limit: int, offset: int
) -> dict:
    """Blends whose stored name or default member name matches.

    Groups have no public flag, so this is only blends the caller belongs to.
    shortcut: filtered in memory. Fine while a person is in a handful of
    blends (free cap 4, premium 12). Filter in SQL if public blends exist.
    """
    group_ids = [
        row[0]
        for row in db.query(GroupMember.group_id)
        .filter(GroupMember.user_id == user_id)
        .all()
    ]
    if not group_ids:
        return {"groups": [], "total": 0}

    groups = (
        db.query(Group).filter(Group.id.in_(group_ids)).order_by(Group.id).all()
    )
    member_rows = (
        db.query(GroupMember, Profile)
        .join(Profile, GroupMember.user_id == Profile.id)
        .filter(GroupMember.group_id.in_(group_ids))
        .order_by(GroupMember.joined_at, GroupMember.user_id)
        .all()
    )
    members_by_group: dict[int, list[Profile]] = defaultdict(list)
    for gm, profile in member_rows:
        members_by_group[gm.group_id].append(profile)

    needle = query.strip().lower()
    matched = []
    for group in groups:
        people = members_by_group.get(group.id, [])
        first_names = [first_name(p.display_name, p.username) for p in people]
        stored = group.name or ""
        default_name = default_blend_name(first_names)
        if needle not in stored.lower() and needle not in default_name.lower():
            continue
        matched.append(
            {
                "id": group.id,
                "name": group.name,
                "display_name": blend_display_name(group.name, first_names),
                "created_by": str(group.created_by),
                "member_count": len(people),
                "member_avatars": [p.avatar_url for p in people[:4]],
                "created_at": group.created_at,
            }
        )

    return {"groups": matched[offset : offset + limit], "total": len(matched)}


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
        group.name = fields["name"].strip() or None

    db.commit()
    db.refresh(group)
    return _group_detail(group, db)


def add_member(group_id: int, user_id: str, username: str, db: Session) -> dict:
    """Add a member by username. Caller must be a member."""
    # Lock the group before the cap check so simultaneous adds serialize.
    group = db.query(Group).filter(Group.id == group_id).with_for_update().first()
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
) -> dict:
    """Generate group recommendations using the shared pipeline."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )

    _verify_membership(group_id, user_id, db)

    members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    # Hidden and test members do not contribute taste, watches, or genre signals.
    member_ids = visible_user_ids([str(m.user_id) for m in members], db)

    if not member_ids:
        return {"results": []}

    # Batch fetch all member profiles in one query
    profiles = db.query(Profile).filter(Profile.id.in_(member_ids)).all()
    profile_map = {str(p.id): p for p in profiles}

    # Each member's own taste: cached profile embedding, else their rated movies.
    member_pos: dict[str, np.ndarray] = {}
    member_neg: dict[str, np.ndarray] = {}
    for mid in member_ids:
        profile = profile_map.get(mid)
        if profile and profile.taste_embedding is not None:
            member_pos[mid] = np.array(list(profile.taste_embedding))
        if profile and profile.negative_embedding is not None:
            member_neg[mid] = np.array(list(profile.negative_embedding))

    missing = [mid for mid in member_ids if mid not in member_pos]
    if missing:
        # Fallback: build from rated movies directly (single batch query)
        per_member_limit = max(5, 50 // len(member_ids))
        all_rows = (
            db.query(
                WatchedMovie.user_id, WatchedMovie.rating, MovieEmbedding.embedding
            )
            .join(MovieEmbedding, WatchedMovie.tmdb_id == MovieEmbedding.tmdb_id)
            .filter(
                WatchedMovie.user_id.in_(missing),
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
        for mid in missing:
            rows = rows_by_member.get(mid, [])
            if not rows:
                continue
            ratings = np.array([r for r, _ in rows])
            embeddings = np.array([e for _, e in rows])
            if ratings.sum() == 0:
                continue
            member_pos[mid] = np.average(embeddings, axis=0, weights=ratings)

    if not member_pos:
        return {"results": []}

    group_positive = np.mean(list(member_pos.values()), axis=0).tolist()
    group_negative = (
        np.mean(list(member_neg.values()), axis=0).tolist() if member_neg else None
    )

    # Union of all members' watched + hidden + group watchlist IDs (single query)
    exclude_stmts = [
        select(WatchedMovie.tmdb_id).where(WatchedMovie.user_id.in_(member_ids)),
        select(HiddenMovie.tmdb_id).where(HiddenMovie.user_id.in_(member_ids)),
        select(InterestedMovie.tmdb_id).where(InterestedMovie.user_id.in_(member_ids)),
        # "Not for me" from any member keeps the movie out of the blend.
        select(MovieInteraction.tmdb_id).where(
            MovieInteraction.user_id.in_(member_ids),
            MovieInteraction.interaction_type == "not_for_me",
        ),
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

    # Per-member signal context: favourite genres from the profile, directors and
    # cast from that member's own top 10 rated movies (one query for everyone).
    top_rows = (
        db.query(WatchedMovie.user_id, Movie)
        .join(Movie, WatchedMovie.tmdb_id == Movie.tmdb_id)
        .filter(
            WatchedMovie.user_id.in_(member_ids),
            WatchedMovie.rating.isnot(None),
        )
        .order_by(WatchedMovie.user_id, WatchedMovie.rating.desc())
        .all()
    )
    top_by_member: dict[str, list[Movie]] = defaultdict(list)
    for uid, movie in top_rows:
        if len(top_by_member[str(uid)]) < 10:
            top_by_member[str(uid)].append(movie)

    member_tastes: list[MemberTaste] = []
    all_genres: list[str] = []
    all_directors: set[str] = set()
    all_cast: set[str] = set()
    for mid in member_ids:
        profile = profile_map.get(mid)
        genres = list(profile.favorite_genres) if profile and profile.favorite_genres else []
        directors: set[str] = set()
        cast: set[str] = set()
        for m in top_by_member.get(mid, []):
            if m.director:
                directors.add(m.director.lower())
            for c in (m.cast or [])[:5]:
                name = c.get("name", "")
                if name:
                    cast.add(name.lower())
        all_genres.extend(genres)
        all_directors |= directors
        all_cast |= cast
        if mid in member_pos:
            member_tastes.append(
                MemberTaste(
                    user_id=mid,
                    embedding=member_pos[mid].tolist(),
                    negative_embedding=(
                        member_neg[mid].tolist() if mid in member_neg else None
                    ),
                    genres=genres,
                    directors=directors,
                    cast=cast,
                )
            )
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
        cf_user_ids=[str(mid) for mid in member_ids],
        members=member_tastes,
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
    # Same visibility rule as blend recommendations: hidden taste is not a signal.
    member_ids = visible_user_ids([str(m.user_id) for m in members], db)

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
        .order_by(GroupMember.joined_at, GroupMember.user_id)
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
        "display_name": _people_display_name(
            group.name, [p for _, p in members_rows]
        ),
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
