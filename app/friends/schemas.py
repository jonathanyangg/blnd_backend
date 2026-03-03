from datetime import datetime

from pydantic import BaseModel


class SendFriendRequestRequest(BaseModel):
    addressee_username: str


class FriendResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


class FriendRequestResponse(BaseModel):
    id: int
    requester: FriendResponse
    addressee: FriendResponse
    status: str
    created_at: datetime


class FriendListResponse(BaseModel):
    friends: list[FriendResponse]


class PendingRequestsResponse(BaseModel):
    incoming: list[FriendRequestResponse]
    outgoing: list[FriendRequestResponse]
