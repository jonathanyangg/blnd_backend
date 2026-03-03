from pydantic import BaseModel


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


class MovieSearchResult(BaseModel):
    results: list[MovieResponse]
    total_results: int
