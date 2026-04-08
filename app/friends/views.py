from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.rate_limit import LIMIT_DEFAULT, LIMIT_IMPORT, limiter
from app.dependencies import get_current_user, get_db
from app.friends import schemas, services

router = APIRouter()


@router.post("/request", response_model=schemas.FriendRequestResponse)
@limiter.limit(LIMIT_DEFAULT)
async def send_friend_request(
    request: Request,
    body: schemas.SendFriendRequestRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.send_friend_request(user_id, body.addressee_username, db)


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


@router.delete("/{friendship_id}/withdraw", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
async def withdraw_friend_request(
    request: Request,
    friendship_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.withdraw_friend_request(user_id, friendship_id, db)


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
