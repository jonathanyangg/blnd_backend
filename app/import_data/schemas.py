from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class SeedStatusResponse(BaseModel):
    status: str
    min_popularity: float | None = None


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


# --- Notes import ---


class ImportNotesRequest(BaseModel):
    """Free-form note text. 50_000 matches the iOS client's own cap."""

    text: str = Field(min_length=1, max_length=50_000)


class ParsedTitle(BaseModel):
    raw_line: str
    title: str
    year: int | None = None


class NotesMovie(BaseModel):
    """Movie object the iOS notes screen decodes. No other fields."""

    tmdb_id: int
    title: str
    year: int | None = None
    poster_path: str | None = None


class NotesImportItem(BaseModel):
    query: str
    confidence: Literal["high", "low", "none"]
    candidates: list[NotesMovie]


class ImportNotesResponse(BaseModel):
    items: list[NotesImportItem]


class NotesCommitRequest(BaseModel):
    bucket: Literal["watched", "watchlist", "interested"]
    tmdb_ids: list[int] = Field(min_length=1, max_length=100)


class NotesCommitResponse(BaseModel):
    saved: int
    recommendations: list[NotesMovie]
