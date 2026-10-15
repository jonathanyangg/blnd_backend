from pydantic import BaseModel, Field


class YearCounts(BaseModel):
    watched: int
    rated: int
    liked: int
    minutes: int


class RatedTitle(BaseModel):
    tmdb_id: int
    title: str
    poster_path: str | None = None
    year: int | None = None
    rating: float


class NamedCount(BaseModel):
    name: str
    count: int


class MonthWatchTime(BaseModel):
    month: int
    count: int
    minutes: int


class YearInReviewResponse(BaseModel):
    year: int
    counts: YearCounts
    top_rated: list[RatedTitle]
    top_genres: list[NamedCount]
    top_directors: list[NamedCount]
    monthly: list[MonthWatchTime]


class BreakdownItem(BaseModel):
    name: str
    count: int
    avg_rating: float | None = None
    minutes: int


class GenreBreakdownResponse(BaseModel):
    genres: list[BreakdownItem]


class DirectorBreakdownResponse(BaseModel):
    directors: list[BreakdownItem]


class SharedRating(BaseModel):
    tmdb_id: int
    title: str
    poster_path: str | None = None
    my_rating: float
    their_rating: float


class GenreOverlap(BaseModel):
    name: str
    my_count: int
    their_count: int


class MatchResponse(BaseModel):
    user_id: str
    username: str
    display_name: str | None = None
    match_percent: int = Field(ge=0, le=100)
    shared_high_ratings: list[SharedRating]
    genre_overlap: list[GenreOverlap]
    biggest_disagreements: list[SharedRating]
