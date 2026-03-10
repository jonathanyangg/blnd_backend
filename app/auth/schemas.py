import re

from pydantic import BaseModel, Field, field_validator

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._]+$")
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


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    taste_bio: str | None = None
    favorite_genres: list[str] = []


class UserSearchResponse(BaseModel):
    results: list[UserResponse]


class UpdateProfileRequest(BaseModel):
    username: str | None = None
    display_name: str | None = Field(default=None, max_length=100)
    avatar_url: str | None = None
    favorite_genres: list[str] | None = Field(default=None, max_length=20)

    @field_validator("username")
    @classmethod
    def check_username(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_username(v)

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
