from pydantic import BaseModel


class LikeActorRequest(BaseModel):
    name: str
    profile_path: str | None = None


class LikedActorResponse(BaseModel):
    tmdb_person_id: int
    name: str
    profile_path: str | None = None
    liked_at: str


class LikedActorsListResponse(BaseModel):
    results: list[LikedActorResponse]
    total: int
