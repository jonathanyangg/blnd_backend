from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class TimelinePerson(BaseModel):
    user_id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


class TimelineItem(BaseModel):
    media_type: Literal["movie", "tv"]
    id: int
    tmdb_id: int
    title: str
    poster_path: str | None = None
    rating: float | None = None
    watched_date: date | None = None
    created_at: datetime | None = None
    user: TimelinePerson
    watched_with: list[TimelinePerson]


class TimelineResponse(BaseModel):
    results: list[TimelineItem]
    next_cursor: str | None = None
