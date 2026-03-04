from pydantic import BaseModel


class RecommendedMovieResponse(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    overview: str | None = None
    poster_path: str | None = None
    genres: list[dict] = []
    director: str | None = None
    similarity: float


class RecommendationsResponse(BaseModel):
    results: list[RecommendedMovieResponse]
    taste_bio: str | None = None
