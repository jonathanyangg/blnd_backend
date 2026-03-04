from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.dependencies import supabase


def signup(
    email: str, password: str, username: str, display_name: str | None, db: Session
) -> dict:
    """Create user via Supabase Auth and insert profile via SQLAlchemy."""
    auth_response = supabase.auth.sign_up({"email": email, "password": password})
    if not auth_response.user or not auth_response.session:
        raise ValueError("Signup failed")

    user_id = auth_response.user.id

    profile = Profile(
        id=user_id,
        username=username,
        display_name=display_name,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    return {
        "access_token": auth_response.session.access_token,
        "refresh_token": auth_response.session.refresh_token,
        "user_id": str(user_id),
    }


def login(email: str, password: str) -> dict:
    """Login via Supabase Auth."""
    auth_response = supabase.auth.sign_in_with_password(
        {"email": email, "password": password}
    )
    if not auth_response.user or not auth_response.session:
        raise ValueError("Login failed")

    return {
        "access_token": auth_response.session.access_token,
        "refresh_token": auth_response.session.refresh_token,
        "user_id": str(auth_response.user.id),
    }


def get_profile(user_id: str, db: Session) -> Profile | None:
    return db.query(Profile).filter(Profile.id == user_id).first()


def update_profile(
    user_id: str, updates: dict, db: Session
) -> tuple[Profile | None, bool]:
    """Update profile fields. Returns (profile, genres_changed)."""
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        return None, False

    genres_changed = False

    if "display_name" in updates:
        profile.display_name = updates["display_name"]
    if "favorite_genres" in updates:
        old_genres = profile.favorite_genres or []
        new_genres = updates["favorite_genres"]
        if set(old_genres) != set(new_genres):
            genres_changed = True
        profile.favorite_genres = new_genres

    db.commit()
    db.refresh(profile)
    return profile, genres_changed
