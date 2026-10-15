"""Shared Movies / TV / All filter for list and recommendation routes.

The iOS sheet sends media_type, year_min, and year_max only when that bound
is set. A missing param leaves the route as it was: movie lists stay movies,
TV search stays TV, and no year bound is applied.

media_type=tv is 404 when TV_SUPPORT_ENABLED is off, the same response the
TV routes use. media_type=all asks a movie route to include TV as well.

year_min and year_max are inclusive. The iOS chips send those bounds
directly (new releases is the calendar year, classics is year_max=1989).
The older decade query is still accepted: new is the current year and the
year before, 2010s is 2010-2019, 2000s is 2000-2009, classic is 1979 and
earlier. An explicit range that does not overlap the preset is 422.
"""

from datetime import date
from typing import Literal

from fastapi import HTTPException, Query
from pydantic import BaseModel

from app.config import settings

MediaType = Literal["movie", "tv", "all"]
Decade = Literal["new", "2010s", "2000s", "classic"]


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
        """True only when the caller asked for TV. Omitted means leave the route alone."""
        return settings.tv_support_enabled and self.media_type in ("tv", "all")


def _decade_window(decade: Decade, today: date) -> tuple[int | None, int | None]:
    if decade == "new":
        return today.year - 1, today.year
    if decade == "2010s":
        return 2010, 2019
    if decade == "2000s":
        return 2000, 2009
    return None, 1979


def _intersect(
    left: tuple[int | None, int | None], right: tuple[int | None, int | None]
) -> tuple[int | None, int | None]:
    ymin = (
        left[0]
        if right[0] is None
        else right[0]
        if left[0] is None
        else max(left[0], right[0])
    )
    ymax = (
        left[1]
        if right[1] is None
        else right[1]
        if left[1] is None
        else min(left[1], right[1])
    )
    if ymin is not None and ymax is not None and ymin > ymax:
        raise HTTPException(
            status_code=422, detail="year_min cannot be greater than year_max"
        )
    return ymin, ymax


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
    decade: str | None = Query(default=None),
) -> ContentFilters:
    """Parse the shared filter query params. Invalid values are 422."""
    if media_type is not None and media_type not in ("movie", "tv", "all"):
        raise HTTPException(
            status_code=422, detail="media_type must be movie, tv, or all"
        )
    if decade is not None and decade not in ("new", "2010s", "2000s", "classic"):
        raise HTTPException(
            status_code=422, detail="decade must be new, 2010s, 2000s, or classic"
        )
    if year_min is not None and year_max is not None and year_min > year_max:
        raise HTTPException(
            status_code=422, detail="year_min cannot be greater than year_max"
        )
    if media_type == "tv" and not settings.tv_support_enabled:
        raise HTTPException(status_code=404, detail="TV support is disabled")

    window = (year_min, year_max)
    if decade is not None:
        window = _intersect(window, _decade_window(decade, date.today()))  # type: ignore[arg-type]
    return ContentFilters(media_type=media_type, year_min=window[0], year_max=window[1])


def year_params(filters: ContentFilters) -> dict[str, int | None]:
    return {"year_min": filters.year_min, "year_max": filters.year_max}
