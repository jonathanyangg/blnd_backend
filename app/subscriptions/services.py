import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.subscriptions.schemas import RevenueCatEvent

logger = logging.getLogger(__name__)

# Event types that grant or extend premium access.
ENTITLEMENT_GRANT_EVENTS = {
    "INITIAL_PURCHASE",
    "RENEWAL",
    "UNCANCELLATION",
    "PRODUCT_CHANGE",
    "NON_RENEWING_PURCHASE",
    "TEMPORARY_ENTITLEMENT_GRANT",
}

# Event types that revoke premium access immediately.
ENTITLEMENT_REVOKE_EVENTS = {
    "EXPIRATION",
    "REFUND",
}


def is_premium(profile: Profile) -> bool:
    """True if the profile holds an active premium entitlement."""
    if profile.subscription_tier != "premium":
        return False
    if profile.subscription_expires_at is None:
        # Admin grants without an expires_at are treated as perpetual.
        return profile.subscription_source == "admin"
    return profile.subscription_expires_at > datetime.now(timezone.utc)


def apply_webhook_event(event: RevenueCatEvent, db: Session) -> None:
    """Mutate the profile's subscription state based on a RevenueCat event.

    RC sends app_user_id as the Supabase user id (iOS sets this at
    Purchases.configure). CANCELLATION does not change state -- access
    persists until expiration. BILLING_ISSUE is soft; RC retries, and a
    following EXPIRATION event ends the entitlement.
    """
    profile = db.query(Profile).filter(Profile.id == event.app_user_id).first()
    if profile is None:
        logger.warning(
            "RevenueCat event %s for unknown user %s", event.type, event.app_user_id
        )
        return

    if event.type in ENTITLEMENT_GRANT_EVENTS:
        profile.subscription_tier = "premium"
        profile.subscription_source = _source_from_store(event.store)
        if event.original_transaction_id:
            profile.subscription_original_transaction_id = event.original_transaction_id
        if event.expiration_at_ms:
            profile.subscription_expires_at = datetime.fromtimestamp(
                event.expiration_at_ms / 1000, tz=timezone.utc
            )
        db.commit()
        logger.info(
            "Granted premium to %s via %s (expires %s)",
            event.app_user_id,
            event.type,
            profile.subscription_expires_at,
        )
    elif event.type in ENTITLEMENT_REVOKE_EVENTS:
        profile.subscription_tier = "free"
        profile.subscription_expires_at = None
        db.commit()
        logger.info("Revoked premium from %s via %s", event.app_user_id, event.type)
    else:
        logger.info(
            "Ignoring RevenueCat event %s for %s (no state change)",
            event.type,
            event.app_user_id,
        )


def admin_grant(user_id: str, days: int, db: Session) -> Profile:
    """Grant premium for `days` days. Used for comping testers/beta users."""
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if profile is None:
        raise ValueError(f"Profile {user_id} not found")
    profile.subscription_tier = "premium"
    profile.subscription_source = "admin"
    profile.subscription_expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    db.commit()
    db.refresh(profile)
    return profile


def _source_from_store(store: str | None) -> str:
    if store in {"APP_STORE", "MAC_APP_STORE"}:
        return "apple"
    if store == "STRIPE":
        return "stripe"
    return "apple"
