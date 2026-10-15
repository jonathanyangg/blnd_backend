from typing import Literal

from pydantic import BaseModel

ShareAudience = Literal["everyone", "friends", "off"]


class RegisterDeviceRequest(BaseModel):
    token: str
    platform: str = "ios"


class MessageResponse(BaseModel):
    message: str


class ChannelFlags(BaseModel):
    """Per-type switches. ``friend_ratings`` is the iOS key.

    Stored as friends_ratings_in_app / friends_ratings_push. ``watched_with``
    is stored as watched_with_tags_in_app / watched_with_tags_push.
    """

    friend_ratings: bool
    blend_activity: bool
    comments_likes: bool
    watched_with: bool
    recommendations: bool


class ChannelFlagsPatch(BaseModel):
    friend_ratings: bool | None = None
    blend_activity: bool | None = None
    comments_likes: bool | None = None
    watched_with: bool | None = None
    recommendations: bool | None = None


class PreferencesResponse(BaseModel):
    """Shipped toggles plus the iOS notification settings.

    ``share_ratings`` (everyone | friends | off) is column
    share_ratings_activity. ``in_app`` and ``push`` are the objects the app
    sends; see ChannelFlags for the column names that differ.
    """

    friend_requests: bool
    group_invites: bool
    recommendations: bool
    friend_activity: bool
    comment_replies: bool
    share_ratings: ShareAudience
    in_app: ChannelFlags
    push: ChannelFlags


class UpdatePreferencesRequest(BaseModel):
    friend_requests: bool | None = None
    group_invites: bool | None = None
    recommendations: bool | None = None
    friend_activity: bool | None = None
    comment_replies: bool | None = None
    share_ratings: ShareAudience | None = None
    in_app: ChannelFlagsPatch | None = None
    push: ChannelFlagsPatch | None = None


class DigestStatusResponse(BaseModel):
    status: str


# --- Inbox ---


class InboxActor(BaseModel):
    id: str
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None


class InboxTarget(BaseModel):
    """Where a tap on the row should open."""

    type: str
    id: str


class InboxItemResponse(BaseModel):
    id: int
    type: str
    from_username: str | None = None
    from_avatar_url: str | None = None
    avatar_url: str | None = None
    poster_url: str | None = None
    group_key: str | None = None
    target: InboxTarget | None = None
    title: str
    body: str
    data: dict = {}
    read: bool
    created_at: str
    actors: list[InboxActor] = []
    actor_count: int = 1
    actions: list[str] = []


class InboxResponse(BaseModel):
    results: list[InboxItemResponse]
    unread_count: int
    next_cursor: str | None = None


class InboxReadResponse(BaseModel):
    message: str
    unread_count: int
