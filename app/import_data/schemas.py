from pydantic import BaseModel, Field
from datetime import date


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
    text: str = Field(min_length=1, max_length=20_000)


class ParsedTitle(BaseModel):
    raw_line: str
    title: str
    year: int | None = None


class ImportedNoteMovie(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    poster_path: str | None = None
    raw_line: str


class UnmatchedNoteLine(BaseModel):
    raw_line: str
    cleaned_title: str


class ImportNotesResponse(BaseModel):
    added: list[ImportedNoteMovie]
    already_in_watchlist: list[ImportedNoteMovie]
    unmatched: list[UnmatchedNoteLine]
    truncated: bool = False
