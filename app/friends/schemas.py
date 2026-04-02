from datetime import datetime

from pydantic import BaseModel, Field


class SendFriendRequestRequest(BaseModel):
    addressee_username: str = Field(max_length=30)


class FriendResponse(BaseModel):
    friendship_id: int | None = None
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


# --- Contact Discovery ---


class UploadContactsRequest(BaseModel):
    phone_numbers: list[str] = Field(max_length=5000)


class SuggestedFriendResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    source: str  # "contact" | "mutual"
    mutual_count: int = 0


class FriendSuggestionsResponse(BaseModel):
    contacts: list[SuggestedFriendResponse]
    mutuals: list[SuggestedFriendResponse]


class MutualFriendResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


class MutualFriendsResponse(BaseModel):
    mutuals: list[MutualFriendResponse]
    count: int
