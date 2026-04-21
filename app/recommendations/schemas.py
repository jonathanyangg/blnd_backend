from pydantic import BaseModel, Field


class FeedRequest(BaseModel):
    exclude: list[int] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=200)


class RecommendedMovieResponse(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    overview: str | None = None
    poster_path: str | None = None
    genres: list[dict] = []
    runtime: int | None = None
    vote_average: float | None = None
    trailer_url: str | None = None
    director: str | None = None
    cast: list[dict] = []
    tagline: str | None = None
    backdrop_path: str | None = None
    match_score: float


class RecommendationsResponse(BaseModel):
    results: list[RecommendedMovieResponse]
    taste_bio: str | None = None


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=200)
    limit: int = Field(default=30, ge=10, le=50)
    exclude: list[int] = Field(default_factory=list)


class SemanticSearchResultItem(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    overview: str | None = None
    poster_path: str | None = None
    genres: list[dict] = []
    runtime: int | None = None
    vote_average: float | None = None
    trailer_url: str | None = None
    director: str | None = None
    cast: list[dict] = []
    tagline: str | None = None
    backdrop_path: str | None = None
    match_score: float
    match_reasoning: str = ""


class SemanticSearchResponse(BaseModel):
    query: str
    results: list[SemanticSearchResultItem]


class HiddenMovieResponse(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    poster_path: str | None = None
    hidden_at: str


class HiddenMoviesListResponse(BaseModel):
    results: list[HiddenMovieResponse]
    total: int
