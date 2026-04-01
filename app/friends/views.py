import asyncio

from aioapns import APNs
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.database import SessionLocal
from app.dependencies import get_apns_client, get_current_user, get_db
from app.friends import schemas, services
from app.notifications import services as notification_services
from app.notifications.services import THREAD_FRIEND_REQUESTS

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

    # Gather data for notification (must happen before response returns)
    addressee_id = result.get("addressee", {}).get("id", "")
    requester_username = result.get("requester", {}).get("username", "")

    if addressee_id and requester_username:

        async def _send_friend_request_push() -> None:
            bg_db = SessionLocal()
            try:
                await notification_services.send_push(
                    user_id=addressee_id,
                    notification_type="friend_requests",
                    title="Friend Request",
                    body=f"{requester_username} sent you a friend request",
                    data={"type": "friend_request", "user_id": user_id},
                    db=bg_db,
                    apns_client=apns_client,
                    thread_id=THREAD_FRIEND_REQUESTS,
                )
            except Exception:
                pass  # Fire-and-forget; send_push logs its own errors
            finally:
                bg_db.close()

        asyncio.ensure_future(_send_friend_request_push())

    return result


@router.post("/{friendship_id}/accept", response_model=schemas.FriendRequestResponse)
@limiter.limit(LIMIT_DEFAULT)
async def accept_friend_request(
    request: Request,
    friendship_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.accept_friend_request(user_id, friendship_id, db)


@router.post("/{friendship_id}/reject", response_model=schemas.FriendRequestResponse)
@limiter.limit(LIMIT_DEFAULT)
async def reject_friend_request(
    request: Request,
    friendship_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.reject_friend_request(user_id, friendship_id, db)


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
