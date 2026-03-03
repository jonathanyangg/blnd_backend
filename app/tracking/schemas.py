from datetime import date, datetime

from pydantic import BaseModel, Field


class TrackMovieRequest(BaseModel):
    tmdb_id: int
    rating: float | None = Field(default=None, ge=0.5, le=5.0)
    review: str | None = None
    watched_date: date | None = None


class UpdateTrackingRequest(BaseModel):
    rating: float | None = Field(default=None, ge=0.5, le=5.0)
    review: str | None = None
    watched_date: date | None = None


class WatchedMovieResponse(BaseModel):
    id: int
    tmdb_id: int
    title: str
    poster_path: str | None = None
    rating: float | None = None
    review: str | None = None
    watched_date: date | None = None
    created_at: datetime


class WatchHistoryResponse(BaseModel):
    results: list[WatchedMovieResponse]
    total: int
