import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.phone import normalize_e164

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._]+$")


def validate_phone_number(v: str) -> str:
    """Accept raw E.164, including spaces or dashes. The API hashes it later."""
    return normalize_e164(v)


USERNAME_MIN = 3
USERNAME_MAX = 30


def validate_username(v: str) -> str:
    v = v.strip().lower()
    if len(v) < USERNAME_MIN or len(v) > USERNAME_MAX:
        raise ValueError(f"Username must be {USERNAME_MIN}-{USERNAME_MAX} characters")
    if not USERNAME_RE.match(v):
        raise ValueError(
            "Username can only contain letters, numbers, periods, and underscores"
        )
    if v.startswith(".") or v.startswith("_") or v.endswith(".") or v.endswith("_"):
        raise ValueError("Username cannot start or end with a period or underscore")
    if ".." in v or "__" in v:
        raise ValueError("Username cannot contain consecutive periods or underscores")
    return v


class SignupRequest(BaseModel):
    email: str
    password: str
    username: str
    display_name: str | None = Field(default=None, max_length=100)
    phone_number: str | None = None

    @field_validator("phone_number")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        if v and v.strip():
            return validate_phone_number(v)
        return None

    @field_validator("username")
    @classmethod
    def check_username(cls, v: str) -> str:
        return validate_username(v)

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str


class MessageResponse(BaseModel):
    message: str


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    taste_bio: str | None = None
    favorite_genres: list[str] = []
    phone_number: str | None = None
    subscription_tier: str = "free"
    subscription_expires_at: datetime | None = None
    followers_count: int = 0
    following_count: int = 0
    is_discoverable: bool = True
    is_premium: bool = False


class UserSearchResponse(BaseModel):
    results: list[UserResponse]
    total: int = 0


class UpdateProfileRequest(BaseModel):
    username: str | None = None
    display_name: str | None = Field(default=None, max_length=100)
    avatar_url: str | None = None
    favorite_genres: list[str] | None = Field(default=None, max_length=20)
    phone_number: str | None = None
    is_discoverable: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_is_test(cls, data: object) -> object:
        """is_test is admin-only. A user cannot set it on their own profile."""
        if isinstance(data, dict) and "is_test" in data:
            raise ValueError("is_test cannot be changed")
        return data

    @field_validator("username")
    @classmethod
    def check_username(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_username(v)

    @field_validator("phone_number")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        # Omitted stays unset. null and "" both mean clear.
        if v is None or not v.strip():
            return None
        return validate_phone_number(v)

    @field_validator("avatar_url")
    @classmethod
    def check_avatar_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.startswith("https://"):
            raise ValueError("Avatar URL must use HTTPS")
        if len(v) > 2048:
            raise ValueError("Avatar URL too long")
        return v

    @field_validator("favorite_genres")
    @classmethod
    def check_genres(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for g in v:
            if len(g) > 50:
                raise ValueError("Genre name too long")
        return v


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def check_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def check_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        return v


class PublicProfileResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    watched_count: int
    friends_count: int
    followers_count: int
    following_count: int
    blends_count: int
    friendship_status: str | None = None
    friendship_id: int | None = None
    is_blocked: bool = False
    subscription_tier: str = "free"


class PublicWatchedMovieResponse(BaseModel):
    tmdb_id: int
    title: str
    poster_path: str | None = None
    rating: float | None = None
    year: int | None = None
    media_type: Literal["movie", "tv"] = "movie"


class PublicWatchedListResponse(BaseModel):
    results: list[PublicWatchedMovieResponse]
    total: int


class PublicFriendResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


class PublicFriendsListResponse(BaseModel):
    friends: list[PublicFriendResponse]


class GenreScore(BaseModel):
    name: str
    score: float
    watch_count: int
    avg_rating: float | None = None


class GenreTasteResponse(BaseModel):
    genres: list[GenreScore]
    total_rated: int


class OAuthRequest(BaseModel):
    provider: Literal["apple"]
    id_token: str
    nonce: str | None = None
    authorization_code: str | None = None


class OAuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str
    is_new_user: bool
    apple_refresh_token: str | None = None


class RatedMovie(BaseModel):
    tmdb_id: int
    rating: float = Field(ge=0.5, le=5.0)


class CompleteOnboardingRequest(BaseModel):
    username: str
    display_name: str | None = Field(default=None, max_length=100)
    favorite_genres: list[str] | None = Field(default=None, max_length=20)
    rated_movies: list[RatedMovie] | None = None
    apple_refresh_token: str | None = None
    phone_number: str | None = None

    @field_validator("username")
    @classmethod
    def check_username(cls, v: str) -> str:
        return validate_username(v)

    @field_validator("phone_number")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_phone_number(v)


class CompleteOnboardingResponse(BaseModel):
    user_id: str
    username: str


class AdminSetTestResponse(BaseModel):
    user_id: str
    is_test: bool
