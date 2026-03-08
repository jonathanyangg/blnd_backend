import os

import jwt
from slowapi import Limiter
from starlette.requests import Request


def _get_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def get_rate_limit_key(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload.get("sub", _get_ip(request))
        except Exception:
            pass
    return _get_ip(request)


limiter = Limiter(
    key_func=get_rate_limit_key,
    enabled=os.environ.get("TESTING", "").lower() != "true",
)

# Rate limit constants
LIMIT_HEAVY = "1/day"
LIMIT_IMPORT = "3/hour"
LIMIT_REFRESH = "5/hour"
LIMIT_SEARCH = "30/minute"
LIMIT_DEFAULT = "60/minute"
