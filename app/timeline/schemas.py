from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class MediaRef(BaseModel):
    tmdb_id: int
    title: str
    poster: str | None = None
    year: int | None = None
    media_type: Literal["movie", "tv"]


class WatchedWithUser(BaseModel):
    id: str
    name: str
    avatar: str | None = None


class TimelineItem(BaseModel):
    id: int
    date: date
    created_at: datetime
    rating: float | None = None
    media: MediaRef
    user: WatchedWithUser
    watched_with: list[WatchedWithUser]


class TimelineResponse(BaseModel):
    results: list[TimelineItem]
    next_cursor: str | None = None
