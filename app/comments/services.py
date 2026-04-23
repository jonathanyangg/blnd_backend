from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.comments.models import CommentLike, MovieComment
from app.tracking.models import WatchedMovie


def _assemble_comment(
    comment: MovieComment,
    profile: Profile | None,
    like_count: int,
    liked_by_me: bool,
    commenter_rating: float | None,
    replies: list[dict],
) -> dict:
    """Assemble a comment dict, masking deleted comment data per D-02."""
    if comment.deleted:
        return {
            "id": comment.id,
            "tmdb_id": comment.tmdb_id,
            "parent_id": comment.parent_id,
            "user_id": None,
            "username": None,
            "avatar_url": None,
            "body": "[deleted]",
            "like_count": 0,
            "liked_by_me": False,
            "commenter_rating": None,
            "is_edited": False,
            "created_at": comment.created_at,
            "replies": replies,
        }
    return {
        "id": comment.id,
        "tmdb_id": comment.tmdb_id,
        "parent_id": comment.parent_id,
        "user_id": str(comment.user_id),
        "username": profile.username if profile else None,
        "avatar_url": profile.avatar_url if profile else None,
        "body": comment.body,
        "like_count": like_count,
        "liked_by_me": liked_by_me,
        "commenter_rating": commenter_rating,
        "is_edited": comment.is_edited,
        "created_at": comment.created_at,
        "replies": replies,
    }


def create_comment(user_id: str, tmdb_id: int, body: str, db: Session) -> dict:
    """Create a top-level comment on a movie."""
    comment = MovieComment(tmdb_id=tmdb_id, user_id=user_id, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)

    profile = db.query(Profile).filter(Profile.id == user_id).first()

    rating_row = (
        db.query(WatchedMovie.rating)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.tmdb_id == tmdb_id)
        .first()
    )
    rating = rating_row.rating if rating_row else None

    return _assemble_comment(
        comment,
        profile,
        like_count=0,
        liked_by_me=False,
        commenter_rating=rating,
        replies=[],
    )


def create_reply(user_id: str, parent_id: int, body: str, db: Session) -> dict:
    """Create a reply to a top-level comment (one level deep only)."""
    parent = db.query(MovieComment).filter(MovieComment.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent comment not found")

    if parent.parent_id is not None:
        raise HTTPException(status_code=400, detail="Cannot reply to a reply")

    reply = MovieComment(
        tmdb_id=parent.tmdb_id, user_id=user_id, parent_id=parent_id, body=body
    )
    db.add(reply)
    db.commit()
    db.refresh(reply)

    profile = db.query(Profile).filter(Profile.id == user_id).first()

    rating_row = (
        db.query(WatchedMovie.rating)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.tmdb_id == parent.tmdb_id)
        .first()
    )
    rating = rating_row.rating if rating_row else None

    return _assemble_comment(
        reply,
        profile,
        like_count=0,
        liked_by_me=False,
        commenter_rating=rating,
        replies=[],
    )


def get_comments(
    user_id: str, tmdb_id: int, limit: int, offset: int, db: Session
) -> dict:
    """Get paginated top-level comments with nested replies and enrichment."""
    # (a) Count all top-level comments (including deleted tombstones) for pagination
    total = (
        db.query(func.count(MovieComment.id))
        .filter(
            MovieComment.tmdb_id == tmdb_id,
            MovieComment.parent_id.is_(None),
        )
        .scalar()
        or 0
    )

    # (b) Fetch top-level comments page (include deleted so tombstones show)
    top_comments = (
        db.query(MovieComment)
        .filter(MovieComment.tmdb_id == tmdb_id, MovieComment.parent_id.is_(None))
        .order_by(MovieComment.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    if not top_comments:
        return {"results": [], "total": total}

    # (c) Fetch all replies for the top-level comment IDs
    top_ids = [c.id for c in top_comments]
    replies = (
        db.query(MovieComment)
        .filter(MovieComment.parent_id.in_(top_ids))
        .order_by(MovieComment.created_at.asc())
        .all()
    )

    # (d) Collect all user IDs
    all_user_ids = list({str(c.user_id) for c in top_comments + replies})

    # (e) Batch fetch profiles
    profiles_map: dict[str, Profile] = (
        {
            str(p.id): p
            for p in db.query(Profile).filter(Profile.id.in_(all_user_ids)).all()
        }
        if all_user_ids
        else {}
    )

    # (f) Batch fetch commenter ratings
    rating_map: dict[str, float] = {}
    if all_user_ids:
        rating_rows = (
            db.query(WatchedMovie.user_id, WatchedMovie.rating)
            .filter(
                WatchedMovie.user_id.in_(all_user_ids),
                WatchedMovie.tmdb_id == tmdb_id,
            )
            .all()
        )
        rating_map = {
            str(r.user_id): r.rating for r in rating_rows if r.rating is not None
        }

    # (g) Batch fetch like counts
    all_comment_ids = [c.id for c in top_comments] + [r.id for r in replies]
    like_counts: dict[int, int] = {}
    if all_comment_ids:
        like_rows = (
            db.query(CommentLike.comment_id, func.count(CommentLike.id).label("cnt"))
            .filter(CommentLike.comment_id.in_(all_comment_ids))
            .group_by(CommentLike.comment_id)
            .all()
        )
        like_counts = {row.comment_id: row.cnt for row in like_rows}

    # (h) Batch fetch liked_by_me
    liked_set: set[int] = set()
    if all_comment_ids:
        liked_set = {
            row.comment_id
            for row in db.query(CommentLike.comment_id)
            .filter(
                CommentLike.user_id == user_id,
                CommentLike.comment_id.in_(all_comment_ids),
            )
            .all()
        }

    # (i) + (j) Assemble replies and group by parent_id
    replies_by_parent: dict[int, list[dict]] = {}
    for reply in replies:
        assembled_reply = _assemble_comment(
            reply,
            profiles_map.get(str(reply.user_id)),
            like_counts.get(reply.id, 0),
            reply.id in liked_set,
            rating_map.get(str(reply.user_id)),
            [],
        )
        pid = reply.parent_id
        if pid is not None:
            if pid not in replies_by_parent:
                replies_by_parent[pid] = []
            replies_by_parent[pid].append(assembled_reply)

    # (k) Assemble top-level comments with embedded replies
    assembled: list[dict] = []
    for top in top_comments:
        assembled.append(
            _assemble_comment(
                top,
                profiles_map.get(str(top.user_id)),
                like_counts.get(top.id, 0),
                top.id in liked_set,
                rating_map.get(str(top.user_id)),
                replies_by_parent.get(top.id, []),
            )
        )

    # (l) Friend-first sort — fetch only friend IDs (not full profiles)
    from sqlalchemy import or_

    from app.friends.models import Friendship

    friendships = (
        db.query(Friendship)
        .filter(
            Friendship.status == "accepted",
            or_(
                Friendship.requester_id == user_id,
                Friendship.addressee_id == user_id,
            ),
        )
        .all()
    )
    friend_ids = {
        str(f.addressee_id) if str(f.requester_id) == user_id else str(f.requester_id)
        for f in friendships
    }

    friend_comments = [
        c for c in assembled if c["user_id"] is not None and c["user_id"] in friend_ids
    ]
    other_comments = [
        c for c in assembled if c["user_id"] is None or c["user_id"] not in friend_ids
    ]

    friend_comments.sort(key=lambda c: c["like_count"], reverse=True)
    other_comments.sort(key=lambda c: c["like_count"], reverse=True)

    sorted_comments = friend_comments + other_comments

    return {"results": sorted_comments, "total": total}


def edit_comment(user_id: str, comment_id: int, body: str, db: Session) -> dict:
    """Edit own comment body. Raises 403 if not owner or comment not found."""
    result: CursorResult = db.execute(  # type: ignore[assignment]
        update(MovieComment)
        .where(
            MovieComment.id == comment_id,
            MovieComment.user_id == user_id,
            MovieComment.deleted == False,  # noqa: E712
        )
        .values(body=body, is_edited=True, updated_at=datetime.now(timezone.utc))
    )
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=403, detail="Not authorized or comment not found"
        )

    comment = db.query(MovieComment).filter(MovieComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    profile = db.query(Profile).filter(Profile.id == user_id).first()

    like_count = (
        db.query(func.count(CommentLike.id))
        .filter(CommentLike.comment_id == comment_id)
        .scalar()
        or 0
    )

    liked_by_me = (
        db.query(CommentLike)
        .filter(CommentLike.user_id == user_id, CommentLike.comment_id == comment_id)
        .first()
        is not None
    )

    rating_row = (
        db.query(WatchedMovie.rating)
        .filter(
            WatchedMovie.user_id == user_id,
            WatchedMovie.tmdb_id == (comment.tmdb_id if comment else 0),
        )
        .first()
    )
    commenter_rating = rating_row.rating if rating_row else None

    return _assemble_comment(
        comment,
        profile,
        like_count,
        liked_by_me,
        commenter_rating,
        [],
    )


def delete_comment(user_id: str, comment_id: int, db: Session) -> None:
    """Soft-delete own comment. Raises 403 if not owner."""
    result: CursorResult = db.execute(  # type: ignore[assignment]
        update(MovieComment)
        .where(MovieComment.id == comment_id, MovieComment.user_id == user_id)
        .values(deleted=True, updated_at=datetime.now(timezone.utc))
    )
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=403, detail="Not authorized or comment not found"
        )


def like_comment(user_id: str, comment_id: int, db: Session) -> dict:
    """Like a comment. Raises 404 if deleted/missing, 400 if already liked."""
    comment = (
        db.query(MovieComment)
        .filter(MovieComment.id == comment_id, MovieComment.deleted == False)  # noqa: E712
        .first()
    )
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    try:
        db.add(CommentLike(comment_id=comment_id, user_id=user_id))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Already liked")

    new_count = (
        db.query(func.count(CommentLike.id))
        .filter(CommentLike.comment_id == comment_id)
        .scalar()
        or 0
    )

    return {"like_count": new_count, "liked_by_me": True}


def unlike_comment(user_id: str, comment_id: int, db: Session) -> dict:
    """Unlike a comment. Raises 404 if like not found."""
    entry = (
        db.query(CommentLike)
        .filter(CommentLike.user_id == user_id, CommentLike.comment_id == comment_id)
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Like not found")

    db.delete(entry)
    db.commit()

    new_count = (
        db.query(func.count(CommentLike.id))
        .filter(CommentLike.comment_id == comment_id)
        .scalar()
        or 0
    )

    return {"like_count": new_count, "liked_by_me": False}


def get_comment_count(tmdb_id: int, db: Session) -> int:
    """Return count of non-deleted comments for a movie."""
    return (
        db.query(func.count(MovieComment.id))
        .filter(MovieComment.tmdb_id == tmdb_id, MovieComment.deleted == False)  # noqa: E712
        .scalar()
        or 0
    )
