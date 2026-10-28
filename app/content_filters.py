"""Optional Movies / TV / year filters.

The iOS sheet sends media_type, year_min, and year_max only when that bound
is set. A missing param leaves the route as it was.

media_type=tv is 404 when TV support is off, matching the TV routes.
media_type=all asks a movie route to include TV as well. year bounds are
inclusive.
"""

from typing import Literal

from fastapi import HTTPException, Query
from pydantic import BaseModel

from app.config import settings

MediaType = Literal["movie", "tv", "all"]


class ContentFilters(BaseModel):
    media_type: MediaType | None = None
    year_min: int | None = None
    year_max: int | None = None

    @property
    def wants_movies(self) -> bool:
        """True unless the caller asked for TV only."""
        return self.media_type in (None, "movie", "all")

    @property
    def wants_tv(self) -> bool:
        """True only when the caller asked for TV."""
        return settings.tv_support_enabled and self.media_type in ("tv", "all")


def year_in_range(year: int | None, year_min: int | None, year_max: int | None) -> bool:
    """Inclusive. A bound with no year on the row does not match."""
    if year_min is None and year_max is None:
        return True
    if year is None:
        return False
    if year_min is not None and year < year_min:
        return False
    if year_max is not None and year > year_max:
        return False
    return True


def get_content_filters(
    media_type: str | None = Query(default=None),
    year_min: int | None = Query(default=None, ge=1888, le=2100),
    year_max: int | None = Query(default=None, ge=1888, le=2100),
) -> ContentFilters:
    """Parse the shared filter query params. Invalid values are 422."""
    if media_type is not None and media_type not in ("movie", "tv", "all"):
        raise HTTPException(
            status_code=422, detail="media_type must be movie, tv, or all"
        )
    if year_min is not None and year_max is not None and year_min > year_max:
        raise HTTPException(
            status_code=422, detail="year_min cannot be greater than year_max"
        )
    if media_type == "tv" and not settings.tv_support_enabled:
        raise HTTPException(status_code=404, detail="TV support is disabled")
    return ContentFilters(media_type=media_type, year_min=year_min, year_max=year_max)
