from aioapns import APNs
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.analytics import Event, track
from app.core.rate_limit import LIMIT_DEFAULT, LIMIT_IMPORT, limiter
from app.dependencies import get_apns_client, get_current_user, get_db
from app.friends import schemas, services
from app.notifications.services import THREAD_FRIEND_REQUESTS, fire_notification

router = APIRouter()


@router.post("/request", response_model=schemas.FriendRequestResponse)
@limiter.limit(LIMIT_DEFAULT)
async def send_friend_request(
    request: Request,
    body: schemas.SendFriendRequestRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    apns_client: APNs | None = Depends(get_apns_client),
):
    result = services.send_friend_request(user_id, body.addressee_username, db)
    track(user_id, Event.FRIEND_REQUEST_SENT)

    # Gather data for notification (must happen before response returns)
    addressee_id = result.get("addressee", {}).get("id", "")
    requester_username = result.get("requester", {}).get("username", "")

    if addressee_id and requester_username:
        fire_notification(
            to=addressee_id,
            from_user=user_id,
            notification_type="friend_requests",
            title="Friend Request",
            body=f"{requester_username} sent you a friend request",
            data={"type": "friend_request", "user_id": user_id},
            thread=THREAD_FRIEND_REQUESTS,
            apns_client=apns_client,
            db=db,
        )

    return result


@router.post("/{friendship_id}/accept", response_model=schemas.FriendRequestResponse)
@limiter.limit(LIMIT_DEFAULT)
async def accept_friend_request(
    request: Request,
    friendship_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    apns_client: APNs | None = Depends(get_apns_client),
):
    result = services.accept_friend_request(user_id, friendship_id, db)
    track(user_id, Event.FRIEND_REQUEST_ACCEPTED)

    # Notify the requester that their request was accepted
    requester_id = result.get("requester", {}).get("id", "")
    accepter_username = result.get("addressee", {}).get("username", "")

    if requester_id and accepter_username:
        fire_notification(
            to=requester_id,
            from_user=user_id,
            notification_type="friend_requests",
            title="Friend Request Accepted",
            body=f"{accepter_username} accepted your friend request",
            data={"type": "friend_accepted", "user_id": user_id},
            thread=THREAD_FRIEND_REQUESTS,
            apns_client=apns_client,
            db=db,
        )

    return result


@router.post("/{friendship_id}/reject", response_model=schemas.FriendRequestResponse)
@limiter.limit(LIMIT_DEFAULT)
async def reject_friend_request(
    request: Request,
    friendship_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.reject_friend_request(user_id, friendship_id, db)


@router.delete("/{friendship_id}/withdraw", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
async def withdraw_friend_request(
    request: Request,
    friendship_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.withdraw_friend_request(user_id, friendship_id, db)


# --- Blocking ---


@router.post("/blocks/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
async def block_user(
    request: Request,
    target_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.block_user(user_id, target_id, db)


@router.delete("/blocks/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
async def unblock_user(
    request: Request,
    target_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.unblock_user(user_id, target_id, db)


@router.get("/blocks", response_model=schemas.BlockedUsersResponse)
@limiter.limit(LIMIT_DEFAULT)
async def list_blocked(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.list_blocked_users(user_id, db)


@router.get("/", response_model=schemas.FriendListResponse)
@limiter.limit(LIMIT_DEFAULT)
async def list_friends(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_friends(user_id, db)


@router.get("/requests", response_model=schemas.PendingRequestsResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_pending_requests(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_pending_requests(user_id, db)


@router.delete("/{friendship_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
async def remove_friend(
    request: Request,
    friendship_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.remove_friend(user_id, friendship_id, db)


# --- Contact Discovery ---


@router.post("/contacts", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_IMPORT)
async def upload_contacts(
    request: Request,
    body: schemas.UploadContactsRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload phone numbers from contacts for friend matching."""
    services.upload_contacts(user_id, body.phone_numbers, db)


@router.get("/suggestions", response_model=schemas.FriendSuggestionsResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_suggestions(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get friend suggestions from contacts + mutual friends."""
    return services.get_suggestions(user_id, db)


@router.get("/{user_id}/mutuals", response_model=schemas.MutualFriendsResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_mutual_friends(
    request: Request,
    user_id: str,
    caller_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get mutual friends between current user and target user."""
    return services.get_mutual_friends(caller_id, user_id, db)
