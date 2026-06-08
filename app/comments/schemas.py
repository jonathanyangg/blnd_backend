from datetime import datetime

from pydantic import BaseModel, Field


class CreateCommentRequest(BaseModel):
    tmdb_id: int
    body: str = Field(min_length=1, max_length=250)


class CreateReplyRequest(BaseModel):
    body: str = Field(min_length=1, max_length=250)


class EditCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=250)


class CommentResponse(BaseModel):
    id: int
    tmdb_id: int
    parent_id: int | None = None
    reply_to_user_id: str | None = None
    reply_to_username: str | None = None
    user_id: str | None = None
    username: str | None = None
    avatar_url: str | None = None
    body: str
    like_count: int = 0
    liked_by_me: bool = False
    commenter_rating: float | None = None
    is_edited: bool = False
    created_at: datetime
    replies: list["CommentResponse"] = []


CommentResponse.model_rebuild()


class CommentsListResponse(BaseModel):
    results: list[CommentResponse]
    total: int


class LikeResponse(BaseModel):
    like_count: int
    liked_by_me: bool
