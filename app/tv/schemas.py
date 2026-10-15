from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TVShowResponse(BaseModel):
    tmdb_id: int
    title: str
    media_type: str = "tv"
    year: int | None = None
    overview: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    genres: list[dict] = []
    number_of_seasons: int | None = None
    episode_run_time: int | None = None
    vote_average: float | None = None


class TVSearchResult(BaseModel):
    results: list[TVShowResponse]
    total_results: int


class TrackTVShowRequest(BaseModel):
    rating: float | None = Field(default=None, ge=0.5, le=5.0)
    review: str | None = Field(default=None, max_length=10000)
    watched_date: date | None = None
    source: Literal["manual", "recommendation"] = "manual"


class WatchedTVShowResponse(BaseModel):
    id: int
    tmdb_id: int
    title: str
    rating: float | None = None
    review: str | None = None
    watched_date: date | None = None
    created_at: datetime | None = None
