from pydantic import BaseModel, Field, model_validator

from app.recommendations.schemas import RecommendedMovieResponse


class TastePick(BaseModel):
    tmdb_id: int = Field(gt=0)
    rating: float | None = Field(default=None, ge=0.5, le=5)


class OnboardingTasteRequest(BaseModel):
    """Five or more films. A rating is optional on each one."""

    picks: list[TastePick] = Field(min_length=5, max_length=100)

    @model_validator(mode="after")
    def require_distinct_ids(self) -> "OnboardingTasteRequest":
        ids = [pick.tmdb_id for pick in self.picks]
        if len(ids) != len(set(ids)):
            raise ValueError("tmdb_ids must be unique")
        return self


class SavedTastePick(BaseModel):
    tmdb_id: int
    rating: float | None = None


class OnboardingTasteResponse(BaseModel):
    saved: list[SavedTastePick]
    results: list[RecommendedMovieResponse]
    taste_bio: str | None = None
