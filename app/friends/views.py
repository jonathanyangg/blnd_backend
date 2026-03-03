from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.friends import schemas, services

router = APIRouter()


@router.post("/request", response_model=schemas.FriendRequestResponse)
async def send_friend_request(
    body: schemas.SendFriendRequestRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.send_friend_request(user_id, body.addressee_username, db)


@router.post("/{friendship_id}/accept", response_model=schemas.FriendRequestResponse)
async def accept_friend_request(
    friendship_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.accept_friend_request(user_id, friendship_id, db)


@router.post("/{friendship_id}/reject", response_model=schemas.FriendRequestResponse)
async def reject_friend_request(
    friendship_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.reject_friend_request(user_id, friendship_id, db)


@router.get("/", response_model=schemas.FriendListResponse)
async def list_friends(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_friends(user_id, db)


@router.get("/requests", response_model=schemas.PendingRequestsResponse)
async def get_pending_requests(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_pending_requests(user_id, db)


@router.delete("/{friendship_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_friend(
    friendship_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.remove_friend(user_id, friendship_id, db)
