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
    rating_on: date | None = None
    review_on: date | None = None


# --- Notes import ---


class ImportNotesRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class ParsedTitle(BaseModel):
    raw_line: str
    title: str
    year: int | None = None


class NoteCandidate(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    year: int | None = None
    poster_path: str | None = None
    confidence: float


class NoteLineMatches(BaseModel):
    raw_line: str
    title: str
    year: int | None = None
    candidates: list[NoteCandidate]


class ImportNotesResponse(BaseModel):
    lines: list[NoteLineMatches]
    truncated: bool = False


class NoteConfirmItem(BaseModel):
    tmdb_id: int = Field(gt=0)
    media_type: str = "movie"
    destination: str
    rating: float | None = Field(default=None, ge=0.5, le=5)


class NoteConfirmRequest(BaseModel):
    items: list[NoteConfirmItem] = Field(min_length=1, max_length=100)


class NoteConfirmResponse(BaseModel):
    added: int
    skipped: int
    failed: list[str]
