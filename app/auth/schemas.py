from pydantic import BaseModel


class SignupRequest(BaseModel):
    email: str
    password: str
    username: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    taste_bio: str | None = None
    favorite_genres: list[str] = []


class UpdateProfileRequest(BaseModel):
    display_name: str | None = None
    taste_bio: str | None = None
    favorite_genres: list[str] | None = None
