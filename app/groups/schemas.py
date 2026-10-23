from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class CreateGroupRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=250)


class UpdateGroupRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=250)


class AddMemberRequest(BaseModel):
    username: str


class GroupMemberResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


class GroupResponse(BaseModel):
    id: int
    name: str | None
    display_name: str
    created_by: str
    member_count: int
    member_avatars: list[str | None] = []
    created_at: datetime


class GroupDetailResponse(BaseModel):
    id: int
    name: str | None
    display_name: str
    created_by: str
    members: list[GroupMemberResponse]
    created_at: datetime


class GroupListResponse(BaseModel):
    groups: list[GroupResponse]
    total: int | None = None


class GroupFeedRequest(BaseModel):
    exclude: list[int] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=200)


class GroupRecMovieResponse(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    overview: str | None = None
    poster_path: str | None = None
    genres: list[dict] = []
    runtime: int | None = None
    vote_average: float | None = None
    trailer_url: str | None = None
    director: str | None = None
    cast: list[dict] = []
    tagline: str | None = None
    backdrop_path: str | None = None
    match_score: float
    comment_count: int = 0
    # Why this fits the whole blend. Null for exploration picks.
    reason: str | None = None


class GroupRecommendationsResponse(BaseModel):
    results: list[GroupRecMovieResponse]


class PickMovie(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    poster_path: str | None = None
    overview: str | None = None
    genres: list[dict] = []
    director: str | None = None
    runtime: int | None = None
    vote_average: float | None = None


class VetoItem(BaseModel):
    tmdb_id: int
    title: str
    user_id: str
    username: str
    reason: str


class PickTonightResponse(BaseModel):
    date: date
    pick: PickMovie | None
    vetoes: list[VetoItem]


class VetoRequest(BaseModel):
    tmdb_id: int
    reason: str = Field(min_length=1, max_length=280)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Reason is required")
        return v
