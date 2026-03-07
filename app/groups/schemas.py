from datetime import datetime

from pydantic import BaseModel


class CreateGroupRequest(BaseModel):
    name: str


class UpdateGroupRequest(BaseModel):
    name: str | None = None


class AddMemberRequest(BaseModel):
    username: str


class GroupMemberResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None


class GroupResponse(BaseModel):
    id: int
    name: str
    created_by: str
    member_count: int
    created_at: datetime


class GroupDetailResponse(BaseModel):
    id: int
    name: str
    created_by: str
    members: list[GroupMemberResponse]
    created_at: datetime


class GroupListResponse(BaseModel):
    groups: list[GroupResponse]


class GroupRecMovieResponse(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    overview: str | None = None
    poster_path: str | None = None
    genres: list[dict] = []
    director: str | None = None
    similarity: float
    score: float


class GroupRecommendationsResponse(BaseModel):
    results: list[GroupRecMovieResponse]
