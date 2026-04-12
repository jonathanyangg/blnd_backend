from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TrackMovieRequest(BaseModel):
    tmdb_id: int
    rating: float | None = Field(default=None, ge=0.5, le=5.0)
    review: str | None = Field(default=None, max_length=10000)
    watched_date: date | None = None
    source: Literal["manual", "recommendation"] = "manual"


class UpdateTrackingRequest(BaseModel):
    rating: float | None = Field(default=None, ge=0.5, le=5.0)
    review: str | None = Field(default=None, max_length=10000)
    watched_date: date | None = None


class WatchedMovieResponse(BaseModel):
    id: int
    tmdb_id: int
    title: str
    poster_path: str | None = None
    rating: float | None = None
    review: str | None = None
    watched_date: date | None = None
    liked: bool = False
    created_at: datetime


class WatchHistoryResponse(BaseModel):
    results: list[WatchedMovieResponse]
    total: int


class AddToWatchlistRequest(BaseModel):
    tmdb_id: int
    source: Literal["manual", "recommendation"] = "manual"


class WatchlistMovieResponse(BaseModel):
    id: int
    tmdb_id: int
    title: str
    year: int | None = None
    overview: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    genres: list[dict] = []
    runtime: int | None = None
    vote_average: float | None = None
    trailer_url: str | None = None
    director: str | None = None
    cast: list[dict] = []
    tagline: str | None = None
    added_by: str | None = None
    added_date: date | None = None
    created_at: datetime
    match_score: float | None = None


class WatchlistResponse(BaseModel):
    results: list[WatchlistMovieResponse]
    total: int


class WatchlistStatusResponse(BaseModel):
    personal: bool
    group_ids: list[int]


class FriendWatchedResponse(BaseModel):
    user_id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    rating: float | None = None
    review: str | None = None
    watched_date: date | None = None


class FriendsWhoWatchedResponse(BaseModel):
    results: list[FriendWatchedResponse]
    total: int


# --- Activity Feed ---


class ActivityFeedItemResponse(BaseModel):
    id: int
    user_id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    action: str
    tmdb_id: int
    title: str | None = None
    poster_path: str | None = None
    rating: float | None = None
    created_at: datetime


class ActivityFeedResponse(BaseModel):
    results: list[ActivityFeedItemResponse]
