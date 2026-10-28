from sqlalchemy.orm import Session

from app.subscriptions.schemas import RevenueCatEvent
from app.subscriptions.services import apply_webhook_event


def test_webhook_ignores_non_uuid_app_user(db: Session) -> None:
    """RevenueCat anonymous IDs must not reach the UUID column as a 500."""
    event = RevenueCatEvent(
        type="INITIAL_PURCHASE",
        id="event-1",
        app_user_id="$RCAnonymousID:not-a-user",
    )

    apply_webhook_event(event, db)
