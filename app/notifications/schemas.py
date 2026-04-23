from pydantic import BaseModel


class RegisterDeviceRequest(BaseModel):
    token: str
    platform: str = "ios"


class MessageResponse(BaseModel):
    message: str


class PreferencesResponse(BaseModel):
    friend_requests: bool
    group_invites: bool
    recommendations: bool
    friend_activity: bool
    comment_replies: bool


class UpdatePreferencesRequest(BaseModel):
    friend_requests: bool | None = None
    group_invites: bool | None = None
    recommendations: bool | None = None
    friend_activity: bool | None = None
    comment_replies: bool | None = None


class DigestStatusResponse(BaseModel):
    status: str


# --- Inbox ---


class InboxItemResponse(BaseModel):
    id: int
    type: str
    from_username: str | None = None
    from_avatar_url: str | None = None
    title: str
    body: str
    data: dict = {}
    read: bool
    created_at: str


class InboxResponse(BaseModel):
    results: list[InboxItemResponse]
    unread_count: int
