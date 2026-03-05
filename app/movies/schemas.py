from pydantic import BaseModel, field_validator


class MovieResponse(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    overview: str | None = None
    poster_path: str | None = None
    genres: list[dict] = []
    runtime: int | None = None
    vote_average: float | None = None
    trailer_url: str | None = None

    @field_validator("vote_average", mode="before")
    @classmethod
    def scale_to_five(cls, v: float | None) -> float | None:
        if v is None:
            return None
        return round(v / 2, 1)

    director: str | None = None
    cast: list[dict] = []
    tagline: str | None = None
    backdrop_path: str | None = None
    imdb_id: str | None = None
    match_score: float | None = None


class MovieSearchResult(BaseModel):
    results: list[MovieResponse]
    total_results: int
