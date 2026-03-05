from pydantic import BaseModel
from datetime import date


class SeedStatusResponse(BaseModel):
    status: str


class ImportSummaryResponse(BaseModel):
    imported: int
    skipped: int
    failed: int
    failed_titles: list[str]


class FilmRecord(BaseModel):
    uri: str
    name: str
    year: int | None = None
    rating: float | None = None
    review: str | None = None
    watched_date: date | None = None
    in_watched: bool = False
    in_watchlist: bool = False
    watchlist_date: date | None = None
    liked: bool = False
