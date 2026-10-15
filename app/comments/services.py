import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import func, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.comments.models import CommentLike, MovieComment
from app.tracking.models import WatchedMovie

if TYPE_CHECKING:
    from aioapns import APNs

# @mention tokens: same charset as usernames (letters, digits, period, underscore).
_MENTION_RE = re.compile(r"@([a-zA-Z0-9._]+)")


def _parse_mentions(body: str) -> set[str]:
    """Extract candidate @usernames (lowercased) from a comment body."""
    return {m.lower() for m in _MENTION_RE.findall(body)}


def _movie_title(db: Session, tmdb_id: int) -> str:
    from app.movies.models import Movie

    movie = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
    return movie.title if movie else "a movie"


def _resolve_root_id(db: Session, comment: MovieComment) -> int:
    """Walk up parent_id to the root comment id (for notification deep-links)."""
    current = comment
    while current.parent_id is not None:
        parent = (
            db.query(MovieComment).filter(MovieComment.id == current.parent_id).first()
        )
        if parent is None:
            break
        current = parent
    return current.id


def _notify_mentions(
    db: Session,
    body: str,
    author_id: str,
    author_name: str,
    tmdb_id: int,
    root_comment_id: int,
    exclude: set[str],
    movie_title: str,
    apns_client: "APNs | None",
) -> None:
    """Fire a comment_mentions push to each @mentioned user (deduped, no self)."""
    from app.notifications.services import THREAD_COMMENT_MENTIONS, fire_notification

    usernames = _parse_mentions(body)
    if not usernames:
        return

    mentioned = db.query(Profile).filter(Profile.username.in_(list(usernames))).all()
    for profile in mentioned:
        uid = str(profile.id)
        if uid == author_id or uid in exclude:
            continue
        fire_notification(
            to=uid,
            from_user=author_id,
            notification_type="comment_mentions",
            title="New Mention",
            body=f"{author_name} mentioned you in a comment on {movie_title}",
            data={
                "type": "comment_mention",
                "tmdb_id": str(tmdb_id),
                "comment_id": str(root_comment_id),
            },
            thread=THREAD_COMMENT_MENTIONS,
            apns_client=apns_client,
            db=db,
        )


def _assemble_comment(
    comment: MovieComment,
    profile: Profile | None,
    like_count: int,
    liked_by_me: bool,
    commenter_rating: float | None,
    replies: list[dict],
    reply_to_user_id: str | None = None,
    reply_to_username: str | None = None,
) -> dict:
    """Assemble a comment dict, masking deleted comment data per D-02.

    reply_to_user_id / reply_to_username describe the author of the direct parent
    (derived at read time), so the client can render the "@replying-to" chip.
    """
    if comment.deleted:
        return {
            "id": comment.id,
            "tmdb_id": comment.tmdb_id,
            "parent_id": comment.parent_id,
            "reply_to_user_id": reply_to_user_id,
            "reply_to_username": reply_to_username,
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
        "reply_to_user_id": reply_to_user_id,
        "reply_to_username": reply_to_username,
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


def create_comment(
    user_id: str,
    tmdb_id: int,
    body: str,
    db: Session,
    apns_client: "APNs | None" = None,
) -> dict:
    """Create a top-level comment on a movie and notify any @mentioned users."""
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

    author_name = profile.username if profile else "Someone"
    _notify_mentions(
        db,
        body,
        user_id,
        author_name,
        tmdb_id,
        comment.id,
        exclude=set(),
        movie_title=_movie_title(db, tmdb_id),
        apns_client=apns_client,
    )

    return _assemble_comment(
        comment,
        profile,
        like_count=0,
        liked_by_me=False,
        commenter_rating=rating,
        replies=[],
    )


def create_reply(
    user_id: str,
    parent_id: int,
    body: str,
    db: Session,
    apns_client: "APNs | None" = None,
) -> dict:
    """Create a reply attached to its direct parent comment.

    Depth lives in the data; the root is resolved at read time and the thread is
    flattened to one visual level. Notifies the parent's author (comment_replies)
    plus any @mentioned users (comment_mentions), deduped.
    """
    parent = db.query(MovieComment).filter(MovieComment.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent comment not found")

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

    # "Replying to" chip = the author of the direct parent comment
    reply_to_profile = (
        profile
        if str(parent.user_id) == user_id
        else db.query(Profile).filter(Profile.id == parent.user_id).first()
    )
    reply_to_username = reply_to_profile.username if reply_to_profile else None

    root_id = _resolve_root_id(db, parent)
    movie_title = _movie_title(db, parent.tmdb_id)
    author_name = profile.username if profile else "Someone"

    notified: set[str] = set()
    # Notify the parent author (not self-replies, not deleted parents)
    if str(parent.user_id) != user_id and not parent.deleted:
        from app.notifications.services import (
            THREAD_COMMENT_REPLIES,
            fire_notification,
        )

        fire_notification(
            to=str(parent.user_id),
            from_user=user_id,
            notification_type="comment_replies",
            title="New Reply",
            body=f"{author_name} replied to your comment on {movie_title}",
            data={
                "type": "comment_reply",
                "tmdb_id": str(parent.tmdb_id),
                "comment_id": str(root_id),
            },
            thread=THREAD_COMMENT_REPLIES,
            apns_client=apns_client,
            db=db,
        )
        notified.add(str(parent.user_id))

    # Notify @mentioned users (excluding self and the already-notified parent author)
    _notify_mentions(
        db,
        body,
        user_id,
        author_name,
        parent.tmdb_id,
        root_id,
        exclude=notified,
        movie_title=movie_title,
        apns_client=apns_client,
    )

    return _assemble_comment(
        reply,
        profile,
        like_count=0,
        liked_by_me=False,
        commenter_rating=rating,
        replies=[],
        reply_to_user_id=str(parent.user_id),
        reply_to_username=reply_to_username,
    )


def get_comments(
    user_id: str, tmdb_id: int, limit: int, offset: int, db: Session
) -> dict:
    """Get paginated top-level comments with their full reply thread flattened
    to a single visual level (Instagram-style)."""
    # (a) Fetch all comments for the movie in one flat query, then build the tree
    all_comments = (
        db.query(MovieComment)
        .filter(MovieComment.tmdb_id == tmdb_id)
        .order_by(MovieComment.created_at.asc())
        .all()
    )
    if not all_comments:
        return {"results": [], "total": 0}

    by_id: dict[int, MovieComment] = {c.id: c for c in all_comments}
    children: dict[int, list[MovieComment]] = {}
    roots: list[MovieComment] = []
    for c in all_comments:
        if c.parent_id is None:
            roots.append(c)
        else:
            children.setdefault(c.parent_id, []).append(c)

    total = len(roots)

    # (b) Paginate roots (newest first), then collect each root's flattened subtree
    roots.sort(key=lambda c: c.created_at, reverse=True)
    page_roots = roots[offset : offset + limit]
    if not page_roots:
        return {"results": [], "total": total}

    def flatten_descendants(root: MovieComment) -> list[MovieComment]:
        out: list[MovieComment] = []
        stack = list(children.get(root.id, []))
        while stack:
            node = stack.pop()
            out.append(node)
            stack.extend(children.get(node.id, []))
        out.sort(key=lambda c: c.created_at)
        return out

    replies_by_root: dict[int, list[MovieComment]] = {
        root.id: flatten_descendants(root) for root in page_roots
    }

    rendered = list(page_roots) + [r for reps in replies_by_root.values() for r in reps]
    rendered_ids = [c.id for c in rendered]

    # (c) Collect user ids: comment authors + direct-parent authors (for the chip)
    user_ids: set[str] = {str(c.user_id) for c in rendered}
    for c in rendered:
        if c.parent_id is not None and c.parent_id in by_id:
            user_ids.add(str(by_id[c.parent_id].user_id))

    profiles_map: dict[str, Profile] = (
        {
            str(p.id): p
            for p in db.query(Profile).filter(Profile.id.in_(list(user_ids))).all()
        }
        if user_ids
        else {}
    )

    # (d) Commenter ratings for this movie
    author_ids = list({str(c.user_id) for c in rendered})
    rating_map: dict[str, float] = {}
    if author_ids:
        rating_rows = (
            db.query(WatchedMovie.user_id, WatchedMovie.rating)
            .filter(
                WatchedMovie.user_id.in_(author_ids),
                WatchedMovie.tmdb_id == tmdb_id,
            )
            .all()
        )
        rating_map = {
            str(r.user_id): r.rating for r in rating_rows if r.rating is not None
        }

    # (e) Like counts + liked_by_me over everything we will render
    like_counts: dict[int, int] = {}
    liked_set: set[int] = set()
    if rendered_ids:
        like_rows = (
            db.query(CommentLike.comment_id, func.count(CommentLike.id).label("cnt"))
            .filter(CommentLike.comment_id.in_(rendered_ids))
            .group_by(CommentLike.comment_id)
            .all()
        )
        like_counts = {row.comment_id: row.cnt for row in like_rows}
        liked_set = {
            row.comment_id
            for row in db.query(CommentLike.comment_id)
            .filter(
                CommentLike.user_id == user_id,
                CommentLike.comment_id.in_(rendered_ids),
            )
            .all()
        }

    def assemble(c: MovieComment, replies: list[dict]) -> dict:
        reply_to_uid: str | None = None
        reply_to_username: str | None = None
        if c.parent_id is not None and c.parent_id in by_id:
            parent_author = by_id[c.parent_id]
            reply_to_uid = str(parent_author.user_id)
            rp = profiles_map.get(reply_to_uid)
            reply_to_username = rp.username if rp else None
        return _assemble_comment(
            c,
            profiles_map.get(str(c.user_id)),
            like_counts.get(c.id, 0),
            c.id in liked_set,
            rating_map.get(str(c.user_id)),
            replies,
            reply_to_user_id=reply_to_uid,
            reply_to_username=reply_to_username,
        )

    # (f) Assemble roots with their flattened replies
    assembled: list[dict] = []
    for root in page_roots:
        reps = [assemble(r, []) for r in replies_by_root[root.id]]
        assembled.append(assemble(root, reps))

    # (g) Friend-first sort — fetch only friend IDs (not full profiles)
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
            WatchedMovie.tmdb_id == comment.tmdb_id,
        )
        .first()
    )
    commenter_rating = rating_row.rating if rating_row else None

    # Resolve "replying to" chip from the direct parent, if any
    reply_to_user_id: str | None = None
    reply_to_username: str | None = None
    if comment.parent_id is not None:
        parent_author = (
            db.query(MovieComment).filter(MovieComment.id == comment.parent_id).first()
        )
        if parent_author:
            reply_to_user_id = str(parent_author.user_id)
            pp = db.query(Profile).filter(Profile.id == parent_author.user_id).first()
            reply_to_username = pp.username if pp else None

    return _assemble_comment(
        comment,
        profile,
        like_count,
        liked_by_me,
        commenter_rating,
        [],
        reply_to_user_id=reply_to_user_id,
        reply_to_username=reply_to_username,
    )


def delete_comment(user_id: str, comment_id: int, db: Session) -> None:
    """Soft-delete own comment and its entire reply subtree. Raises 403 if not owner."""
    target = (
        db.query(MovieComment)
        .filter(MovieComment.id == comment_id, MovieComment.user_id == user_id)
        .first()
    )
    if not target:
        raise HTTPException(
            status_code=403, detail="Not authorized or comment not found"
        )

    # Collect the target + all descendants within this movie (small per-movie set)
    rows = (
        db.query(MovieComment.id, MovieComment.parent_id)
        .filter(MovieComment.tmdb_id == target.tmdb_id)
        .all()
    )
    children: dict[int, list[int]] = {}
    for cid, pid in rows:
        if pid is not None:
            children.setdefault(pid, []).append(cid)

    subtree: list[int] = []
    stack = [comment_id]
    while stack:
        cid = stack.pop()
        subtree.append(cid)
        stack.extend(children.get(cid, []))

    db.execute(
        update(MovieComment)
        .where(MovieComment.id.in_(subtree))
        .values(deleted=True, updated_at=datetime.now(timezone.utc))
    )
    db.commit()


def like_comment(
    user_id: str,
    comment_id: int,
    db: Session,
    apns_client: "APNs | None" = None,
) -> dict:
    """Like a comment. Raises 404 if deleted/missing, 400 if already liked.

    Fans the like out to the author's notification inbox (grouped by comment).
    """
    comment = (
        db.query(MovieComment)
        .filter(MovieComment.id == comment_id, MovieComment.deleted == False)  # noqa: E712
        .first()
    )
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    from app.notifications.services import (
        THREAD_COMMENT_LIKES,
        fire_notification,
        is_push_eligible,
        record_comment_like,
    )

    record_comment_like(
        db,
        comment_owner_id=str(comment.user_id),
        comment_id=comment.id,
        tmdb_id=comment.tmdb_id,
        actor_id=user_id,
    )
    try:
        db.add(CommentLike(comment_id=comment_id, user_id=user_id))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Already liked")

    if (
        apns_client is not None
        and str(comment.user_id) != user_id
        and is_push_eligible(str(comment.user_id), "comments_likes", db)
    ):
        actor = db.query(Profile).filter(Profile.id == user_id).first()
        actor_name = (
            (actor.display_name or actor.username) if actor else "Someone"
        )
        fire_notification(
            to=str(comment.user_id),
            from_user=user_id,
            notification_type="comment_like",
            title="New Like",
            body=f"{actor_name} liked your review",
            data={
                "type": "comment_like",
                "tmdb_id": str(comment.tmdb_id),
                "comment_id": str(comment.id),
            },
            thread=THREAD_COMMENT_LIKES,
            apns_client=apns_client,
            skip_inbox=True,
        )

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


def get_comment_counts(tmdb_ids: list[int], db: Session) -> dict[int, int]:
    """Return {tmdb_id: count} of non-deleted comments for the given movies."""
    if not tmdb_ids:
        return {}
    rows = (
        db.query(MovieComment.tmdb_id, func.count(MovieComment.id))
        .filter(MovieComment.tmdb_id.in_(tmdb_ids), MovieComment.deleted == False)  # noqa: E712
        .group_by(MovieComment.tmdb_id)
        .all()
    )
    return {tmdb_id: count for tmdb_id, count in rows}
