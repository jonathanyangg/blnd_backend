import jwt as pyjwt
from slowapi import Limiter
from starlette.requests import Request

from app.config import settings


def get_rate_limit_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = pyjwt.decode(auth[7:], options={"verify_signature": False})
            if sub := payload.get("sub"):
                return f"user:{sub}"
        except Exception:
            pass
    return f"ip:{request.client.host if request.client else 'unknown'}"


limiter = Limiter(
    key_func=get_rate_limit_key,
    enabled=settings.blnd_disable_rate_limits.lower() != "true",
)

# Rate limit constants
LIMIT_HEAVY = "1/day"
LIMIT_IMPORT = "10/hour"
LIMIT_REFRESH = "20/hour"
LIMIT_SEARCH = "30/minute"
LIMIT_AI_SEARCH = "20/hour"
LIMIT_DEFAULT = "60/minute"
