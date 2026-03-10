import os

from slowapi import Limiter
from starlette.requests import Request


def get_rate_limit_key(request: Request) -> str:
    """Rate limit by client IP. Never trust unverified JWT claims."""
    if request.client:
        return request.client.host
    return "unknown"


limiter = Limiter(
    key_func=get_rate_limit_key,
    enabled=os.environ.get("BLND_DISABLE_RATE_LIMITS", "").lower() != "true",
)

# Rate limit constants
LIMIT_HEAVY = "1/day"
LIMIT_IMPORT = "3/hour"
LIMIT_REFRESH = "5/hour"
LIMIT_SEARCH = "30/minute"
LIMIT_DEFAULT = "60/minute"
