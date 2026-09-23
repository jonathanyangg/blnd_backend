import logging
from enum import StrEnum

from posthog import Posthog

from app.config import settings

logger = logging.getLogger(__name__)

_client: Posthog | None = None


class Event(StrEnum):
    # Auth
    SIGNUP_COMPLETED = "signup_completed"
    LOGIN_COMPLETED = "login_completed"
    ONBOARDING_COMPLETED = "onboarding_completed"
    ACCOUNT_DELETED = "account_deleted"

    # Movies
    MOVIE_RATED = "movie_rated"
    MOVIE_HIDDEN = "movie_hidden"
    WATCHLIST_ADDED = "watchlist_added"

    # Social
    FRIEND_REQUEST_SENT = "friend_request_sent"
    FRIEND_REQUEST_ACCEPTED = "friend_request_accepted"
    GROUP_CREATED = "group_created"

    # Features
    LETTERBOXD_IMPORTED = "letterboxd_imported"
    SEMANTIC_DISCOVER_USED = "semantic_discover_used"


def init() -> None:
    global _client
    if not settings.posthog_api_key:
        logger.info("PostHog disabled — no POSTHOG_API_KEY set")
        return
    _client = Posthog(
        project_api_key=settings.posthog_api_key,
        host=settings.posthog_host or "https://us.i.posthog.com",
    )
    logger.info("PostHog initialized")


def shutdown() -> None:
    if _client:
        _client.flush()
        _client.shutdown()


def track(user_id: str, event: Event, properties: dict | None = None) -> None:
    if _client is None:
        return
    _client.capture(
        distinct_id=user_id,
        event=event,
        properties=properties or {},
    )
