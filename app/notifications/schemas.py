from typing import Literal

from pydantic import BaseModel

ShareAudience = Literal["everyone", "friends", "blends", "off"]


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
    share_ratings_activity: ShareAudience
    friends_ratings_in_app: bool
    friends_ratings_push: bool
    blend_activity_in_app: bool
    blend_activity_push: bool
    comments_likes_in_app: bool
    comments_likes_push: bool
    watched_with_tags_in_app: bool
    watched_with_tags_push: bool
    recommendations_in_app: bool
    recommendations_push: bool


class UpdatePreferencesRequest(BaseModel):
    friend_requests: bool | None = None
    group_invites: bool | None = None
    recommendations: bool | None = None
    friend_activity: bool | None = None
    comment_replies: bool | None = None
    share_ratings_activity: ShareAudience | None = None
    friends_ratings_in_app: bool | None = None
    friends_ratings_push: bool | None = None
    blend_activity_in_app: bool | None = None
    blend_activity_push: bool | None = None
    comments_likes_in_app: bool | None = None
    comments_likes_push: bool | None = None
    watched_with_tags_in_app: bool | None = None
    watched_with_tags_push: bool | None = None
    recommendations_in_app: bool | None = None
    recommendations_push: bool | None = None


class DigestStatusResponse(BaseModel):
    status: str


# --- Inbox ---


class InboxActor(BaseModel):
    id: str
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None


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
