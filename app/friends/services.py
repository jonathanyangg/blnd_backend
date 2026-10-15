import uuid as _uuid
from collections import Counter

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.auth.visibility import is_hidden_profile, visible_user_ids
from app.friends.models import Friendship, UserBlock, UserContact


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

    # Cannot send a friend request if either side has blocked the other
    is_blocked_by_me, has_blocked_me = get_block_state(user_id, str(addressee.id), db)
    if is_blocked_by_me or has_blocked_me:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
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


def block_user(user_id: str, target_id: str, db: Session) -> None:
    """Block a user. Auto-removes any existing friendship/request between the two."""
    if target_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot block yourself",
        )

    target = db.query(Profile).filter(Profile.id == target_id).first()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    existing = (
        db.query(UserBlock)
        .filter(UserBlock.blocker_id == user_id, UserBlock.blocked_id == target_id)
        .first()
    )
    if existing:
        return  # Already blocked — idempotent

    # Remove any friendship/request between the two users (either direction)
    db.query(Friendship).filter(
        or_(
            (Friendship.requester_id == user_id)
            & (Friendship.addressee_id == target_id),
            (Friendship.requester_id == target_id)
            & (Friendship.addressee_id == user_id),
        )
    ).delete(synchronize_session=False)

    db.add(UserBlock(blocker_id=user_id, blocked_id=target_id))
    db.commit()


def unblock_user(user_id: str, target_id: str, db: Session) -> None:
    """Unblock a user."""
    block = (
        db.query(UserBlock)
        .filter(UserBlock.blocker_id == user_id, UserBlock.blocked_id == target_id)
        .first()
    )
    if not block:
        return  # Not blocked — idempotent
    db.delete(block)
    db.commit()


def list_blocked_users(user_id: str, db: Session) -> dict:
    """Return all users this user has blocked."""
    blocks = (
        db.query(UserBlock)
        .filter(UserBlock.blocker_id == user_id)
        .order_by(UserBlock.created_at.desc())
        .all()
    )
    if not blocks:
        return {"blocked": []}

    profile_map = {
        p.id: p
        for p in db.query(Profile)
        .filter(Profile.id.in_([b.blocked_id for b in blocks]))
        .all()
    }
    return {
        "blocked": [
            {
                "id": str(p.id),
                "username": p.username,
                "display_name": p.display_name,
                "avatar_url": p.avatar_url,
                "blocked_at": b.created_at,
            }
            for b in blocks
            if (p := profile_map.get(b.blocked_id)) is not None
        ]
    }


def get_block_state(user_id: str, target_id: str, db: Session) -> tuple[bool, bool]:
    """Return (is_blocked_by_me, has_blocked_me) for a target user."""
    rows = (
        db.query(UserBlock)
        .filter(
            or_(
                (UserBlock.blocker_id == user_id) & (UserBlock.blocked_id == target_id),
                (UserBlock.blocker_id == target_id) & (UserBlock.blocked_id == user_id),
            )
        )
        .all()
    )
    is_blocked_by_me = any(str(r.blocker_id) == user_id for r in rows)
    has_blocked_me = any(str(r.blocker_id) == target_id for r in rows)
    return is_blocked_by_me, has_blocked_me


def get_blocked_user_ids(user_id: str, db: Session) -> set[str]:
    """Return IDs of users involved in any block relationship with this user (either direction)."""
    rows = (
        db.query(UserBlock)
        .filter(or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id))
        .all()
    )
    ids: set[str] = set()
    for r in rows:
        if str(r.blocker_id) == user_id:
            ids.add(str(r.blocked_id))
        else:
            ids.add(str(r.blocker_id))
    return ids


def withdraw_friend_request(user_id: str, friendship_id: int, db: Session) -> None:
    """Withdraw a pending outgoing friend request (only requester can withdraw)."""
    friendship = db.query(Friendship).filter(Friendship.id == friendship_id).first()
    if not friendship:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Friend request not found"
        )

    if str(friendship.requester_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the requester can withdraw a friend request",
        )

    if friendship.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot withdraw a request with status '{friendship.status}'",
        )

    db.delete(friendship)
    db.commit()


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

    # Batch fetch all friend profiles in one query
    friend_ids = [
        f.addressee_id if str(f.requester_id) == user_id else f.requester_id
        for f in friendships
    ]
    profiles = db.query(Profile).filter(Profile.id.in_(friend_ids)).all()
    profile_map = {p.id: p for p in profiles}

    friends = []
    for f in friendships:
        friend_id = f.addressee_id if str(f.requester_id) == user_id else f.requester_id
        profile = profile_map.get(friend_id)
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

    # Batch fetch all profiles referenced by pending requests
    all_ids = set()
    for f in incoming + outgoing:
        all_ids.add(f.requester_id)
        all_ids.add(f.addressee_id)
    profiles = db.query(Profile).filter(Profile.id.in_(all_ids)).all()
    profile_map = {p.id: p for p in profiles}

    return {
        "incoming": [_to_request_response(f, profile_map) for f in incoming],
        "outgoing": [_to_request_response(f, profile_map) for f in outgoing],
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


def _to_request_response(
    friendship: Friendship,
    profile_map_or_db: dict | Session,
) -> dict:
    if isinstance(profile_map_or_db, dict):
        requester = profile_map_or_db.get(friendship.requester_id)
        addressee = profile_map_or_db.get(friendship.addressee_id)
    else:
        db = profile_map_or_db
        profiles = (
            db.query(Profile)
            .filter(Profile.id.in_([friendship.requester_id, friendship.addressee_id]))
            .all()
        )
        pmap = {p.id: p for p in profiles}
        requester = pmap.get(friendship.requester_id)
        addressee = pmap.get(friendship.addressee_id)
    return {
        "id": friendship.id,
        "requester": _profile_to_response(requester) if requester else {},
        "addressee": _profile_to_response(addressee) if addressee else {},
        "status": friendship.status,
        "created_at": friendship.created_at,
    }


# --- Contact Discovery ---


def upload_contacts(user_id: str, phone_numbers: list[str], db: Session) -> None:
    """Replace user's stored contacts with the new list."""
    db.query(UserContact).filter(UserContact.user_id == user_id).delete()
    for phone in phone_numbers:
        db.add(UserContact(user_id=user_id, contact_phone=phone))
    db.commit()


def _get_friend_ids(user_id: str, db: Session) -> set[str]:
    """Get IDs of all accepted friends."""
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
    return {
        str(f.addressee_id) if str(f.requester_id) == user_id else str(f.requester_id)
        for f in friendships
    }


def _get_pending_ids(user_id: str, db: Session) -> set[str]:
    """Get IDs of users with pending friend requests (either direction)."""
    pending = (
        db.query(Friendship)
        .filter(
            Friendship.status == "pending",
            or_(
                Friendship.requester_id == user_id,
                Friendship.addressee_id == user_id,
            ),
        )
        .all()
    )
    return {
        str(f.addressee_id) if str(f.requester_id) == user_id else str(f.requester_id)
        for f in pending
    }


def get_contact_suggestions(user_id: str, db: Session) -> list[dict]:
    """Find blnd users who match the uploaded contacts."""
    exclude_ids = (
        _get_friend_ids(user_id, db)
        | _get_pending_ids(user_id, db)
        | get_blocked_user_ids(user_id, db)
    )
    exclude_ids.add(user_id)

    # Get this user's uploaded contact phone numbers
    contact_phones = [
        row[0]
        for row in db.query(UserContact.contact_phone)
        .filter(UserContact.user_id == user_id)
        .all()
    ]
    if not contact_phones:
        return []

    # Match against profiles with phone numbers
    matches = (
        db.query(Profile)
        .filter(
            Profile.phone_number.in_(contact_phones),
            Profile.id.notin_(list(exclude_ids)),
            Profile.is_discoverable.is_(True),
            Profile.is_test.is_(False),
        )
        .limit(50)
        .all()
    )

    return [
        {
            "id": str(p.id),
            "username": p.username,
            "display_name": p.display_name,
            "avatar_url": p.avatar_url,
            "source": "contact",
            "mutual_count": 0,
        }
        for p in matches
    ]


def get_mutual_suggestions(user_id: str, db: Session) -> list[dict]:
    """Find friends-of-friends ranked by mutual friend count."""
    friend_ids = _get_friend_ids(user_id, db)
    if not friend_ids:
        return []

    exclude_ids = (
        friend_ids | _get_pending_ids(user_id, db) | get_blocked_user_ids(user_id, db)
    )
    exclude_ids.add(user_id)

    # For each friend, get their friends (2nd degree connections)
    fof_friendships = (
        db.query(Friendship)
        .filter(
            Friendship.status == "accepted",
            or_(
                Friendship.requester_id.in_(list(friend_ids)),
                Friendship.addressee_id.in_(list(friend_ids)),
            ),
        )
        .all()
    )

    # Count how many mutual friends each 2nd-degree user has
    mutual_counter: Counter[str] = Counter()
    for f in fof_friendships:
        req_id = str(f.requester_id)
        addr_id = str(f.addressee_id)
        # One side is our friend, the other is a potential suggestion
        if req_id in friend_ids and addr_id not in exclude_ids:
            mutual_counter[addr_id] += 1
        elif addr_id in friend_ids and req_id not in exclude_ids:
            mutual_counter[req_id] += 1

    if not mutual_counter:
        return []

    # Hidden and test accounts are not suggestable, and must not take a slot.
    visible = set(visible_user_ids(list(mutual_counter), db))
    for uid in list(mutual_counter):
        if uid not in visible:
            del mutual_counter[uid]
    if not mutual_counter:
        return []

    # Fetch profiles for top suggestions, ranked by mutual count
    top_ids = [uid for uid, _ in mutual_counter.most_common(30)]
    profiles = db.query(Profile).filter(Profile.id.in_(top_ids)).all()
    profile_map = {str(p.id): p for p in profiles}

    results = []
    for uid, count in mutual_counter.most_common(30):
        p = profile_map.get(uid)
        if p:
            results.append(
                {
                    "id": str(p.id),
                    "username": p.username,
                    "display_name": p.display_name,
                    "avatar_url": p.avatar_url,
                    "source": "mutual",
                    "mutual_count": count,
                }
            )
    return results


def get_suggestions(user_id: str, db: Session) -> dict:
    """Combined contact + mutual friend suggestions."""
    contacts = get_contact_suggestions(user_id, db)
    mutuals = get_mutual_suggestions(user_id, db)
    return {"contacts": contacts, "mutuals": mutuals}


def get_mutual_friends(user_id: str, target_id: str, db: Session) -> dict:
    """Get mutual friends between two users."""
    my_friends = _get_friend_ids(user_id, db)
    their_friends = _get_friend_ids(target_id, db)
    mutual_ids = my_friends & their_friends

    if not mutual_ids:
        return {"mutuals": [], "count": 0}

    profiles = db.query(Profile).filter(Profile.id.in_(list(mutual_ids))).all()
    mutuals = [
        {
            "id": str(p.id),
            "username": p.username,
            "display_name": p.display_name,
            "avatar_url": p.avatar_url,
        }
        for p in profiles
        if not is_hidden_profile(p)
    ]
    return {"mutuals": mutuals, "count": len(mutuals)}
