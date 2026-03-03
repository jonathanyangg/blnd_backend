import uuid as _uuid

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.friends.models import Friendship


def send_friend_request(user_id: str, addressee_username: str, db: Session) -> dict:
    """Send a friend request by username."""
    addressee = db.query(Profile).filter(Profile.username == addressee_username).first()
    if not addressee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if str(addressee.id) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot send friend request to yourself",
        )

    # Check existing friendship in either direction
    existing = (
        db.query(Friendship)
        .filter(
            or_(
                (Friendship.requester_id == user_id)
                & (Friendship.addressee_id == addressee.id),
                (Friendship.requester_id == addressee.id)
                & (Friendship.addressee_id == user_id),
            )
        )
        .first()
    )

    if existing:
        if existing.status == "accepted":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Already friends",
            )
        if existing.status == "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Friend request already pending",
            )
        # Status is 'rejected' — allow re-request by resetting
        existing.requester_id = _uuid.UUID(user_id)
        existing.addressee_id = addressee.id
        existing.status = "pending"
        db.commit()
        db.refresh(existing)
        return _to_request_response(existing, db)

    friendship = Friendship(requester_id=user_id, addressee_id=addressee.id)
    db.add(friendship)
    db.commit()
    db.refresh(friendship)
    return _to_request_response(friendship, db)


def accept_friend_request(user_id: str, friendship_id: int, db: Session) -> dict:
    """Accept a pending friend request (only addressee can accept)."""
    friendship = db.query(Friendship).filter(Friendship.id == friendship_id).first()
    if not friendship:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Friend request not found"
        )

    if str(friendship.addressee_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the recipient can accept a friend request",
        )

    if friendship.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot accept a request with status '{friendship.status}'",
        )

    friendship.status = "accepted"
    db.commit()
    db.refresh(friendship)
    return _to_request_response(friendship, db)


def reject_friend_request(user_id: str, friendship_id: int, db: Session) -> dict:
    """Reject a pending friend request (only addressee can reject)."""
    friendship = db.query(Friendship).filter(Friendship.id == friendship_id).first()
    if not friendship:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Friend request not found"
        )

    if str(friendship.addressee_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the recipient can reject a friend request",
        )

    if friendship.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject a request with status '{friendship.status}'",
        )

    friendship.status = "rejected"
    db.commit()
    db.refresh(friendship)
    return _to_request_response(friendship, db)


def get_friends(user_id: str, db: Session) -> dict:
    """Get all accepted friends for a user."""
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

    friends = []
    for f in friendships:
        # The friend is whichever side is NOT the current user
        friend_id = f.addressee_id if str(f.requester_id) == user_id else f.requester_id
        profile = db.query(Profile).filter(Profile.id == friend_id).first()
        if profile:
            friends.append(_profile_to_response(profile, friendship_id=f.id))

    return {"friends": friends}


def get_pending_requests(user_id: str, db: Session) -> dict:
    """Get incoming and outgoing pending friend requests."""
    incoming = (
        db.query(Friendship)
        .filter(
            Friendship.addressee_id == user_id,
            Friendship.status == "pending",
        )
        .all()
    )

    outgoing = (
        db.query(Friendship)
        .filter(
            Friendship.requester_id == user_id,
            Friendship.status == "pending",
        )
        .all()
    )

    return {
        "incoming": [_to_request_response(f, db) for f in incoming],
        "outgoing": [_to_request_response(f, db) for f in outgoing],
    }


def remove_friend(user_id: str, friendship_id: int, db: Session) -> None:
    """Remove an accepted friendship (either party can remove)."""
    friendship = db.query(Friendship).filter(Friendship.id == friendship_id).first()
    if not friendship:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Friendship not found"
        )

    if (
        str(friendship.requester_id) != user_id
        and str(friendship.addressee_id) != user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not part of this friendship",
        )

    if friendship.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only remove accepted friendships",
        )

    db.delete(friendship)
    db.commit()


def _profile_to_response(profile: Profile, *, friendship_id: int | None = None) -> dict:
    data: dict = {
        "id": str(profile.id),
        "username": profile.username,
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
    }
    if friendship_id is not None:
        data["friendship_id"] = friendship_id
    return data


def _to_request_response(friendship: Friendship, db: Session) -> dict:
    requester = db.query(Profile).filter(Profile.id == friendship.requester_id).first()
    addressee = db.query(Profile).filter(Profile.id == friendship.addressee_id).first()
    return {
        "id": friendship.id,
        "requester": _profile_to_response(requester) if requester else {},
        "addressee": _profile_to_response(addressee) if addressee else {},
        "status": friendship.status,
        "created_at": friendship.created_at,
    }
