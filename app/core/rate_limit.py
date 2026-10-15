from limits import parse as parse_limit
from slowapi import Limiter
from starlette.requests import Request

from app.config import settings


def get_rate_limit_key(request: Request) -> str:
    """Key by the user id from a signature-checked JWT. Otherwise the client IP.

    A token whose signature does not verify is not a user key, even if its
    payload names someone. That request shares the IP bucket.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            from app.dependencies import _decode_jwt

            return f"user:{_decode_jwt(auth[7:])}"
        except Exception:
            pass
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


limiter = Limiter(
    key_func=get_rate_limit_key,
    enabled=settings.blnd_disable_rate_limits.lower() != "true",
)

# Rate limit constants
LIMIT_HEAVY = "1/day"
LIMIT_IMPORT = "10/hour"
LIMIT_REFRESH = "20/hour"
LIMIT_SEARCH = "30/minute"
LIMIT_AI_SEARCH = "50/day"  # premium cap applied via decorator
LIMIT_AI_SEARCH_FREE = "2/day"  # free-tier cap enforced in-handler
LIMIT_COMMENT = "20/minute"
LIMIT_DEFAULT = "60/minute"

_FREE_AI_SEARCH_ITEM = parse_limit(LIMIT_AI_SEARCH_FREE)


def check_free_ai_search(user_id: str) -> bool:
    """Returns True if a free-tier user is within their 2/day AI-search budget.

    Increments the counter on success. Always returns True when rate limiting
    is disabled (e.g. tests).
    """
    if not limiter.enabled:
        return True
    return limiter.limiter.hit(_FREE_AI_SEARCH_ITEM, f"user:{user_id}:ai_free")
