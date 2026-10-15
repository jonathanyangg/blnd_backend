from sqlalchemy.orm import Session

from app.actors.services import like_actor
from tests.factories import make_profile


def test_like_actor_is_idempotent(db: Session) -> None:
    """Repeated likes reuse the existing row instead of relying on a race."""
    user_id = "11111111-1111-1111-1111-111111111111"
    make_profile(db, user_id=user_id, username="liker")

    first = like_actor(user_id, 1, "Brad Pitt", "/poster.jpg", db)
    second = like_actor(user_id, 1, "Brad Pitt", "/poster.jpg", db)

    assert first.id == second.id
