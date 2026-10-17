"""Who may show up on social surfaces.

A profile is hidden when the user turned discovery off or an admin marked the
account as a test account. Hidden profiles stay in the database. They are left
out of search, suggestions, social listings, feeds, blend taste, and
notification fan-out. The owner can still load their own profile.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.models import Profile


def is_hidden_profile(profile: Profile) -> bool:
    """True when this account must not appear to other people."""
    return (not profile.is_discoverable) or bool(profile.is_test)


def raise_if_hidden_from(caller_id: str, profile: Profile) -> None:
    """404 when caller is looking at someone else's hidden profile."""
    if str(profile.id) == str(caller_id):
        return
    if is_hidden_profile(profile):
        raise HTTPException(status_code=404, detail="User not found")


def visible_user_ids(user_ids: list[str], db: Session) -> list[str]:
    """Subset of user_ids that may appear on social surfaces, original order kept."""
    if not user_ids:
        return []
    rows = (
        db.query(Profile.id)
        .filter(
            Profile.id.in_(user_ids),
            Profile.is_discoverable.is_(True),
            Profile.is_test.is_(False),
        )
        .all()
    )
    visible = {str(row[0]) for row in rows}
    return [user_id for user_id in user_ids if user_id in visible]


def notify_allowed(from_user_id: str | None, db: Session) -> bool:
    """System notices have no actor and are allowed. Hidden actors are not."""
    if not from_user_id:
        return True
    profile = db.query(Profile).filter(Profile.id == from_user_id).first()
    if profile is None:
        return True
    return not is_hidden_profile(profile)
