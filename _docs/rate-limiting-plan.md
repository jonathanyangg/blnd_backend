# Rate Limiting Plan

## Context

Endpoints hit TMDB and OpenAI APIs with no protection. One bad actor or runaway frontend loop racks up the bill. All endpoints require JWT auth (except signup/login), so we can rate limit per-user. Using `slowapi` with in-memory storage — no Redis needed for single-instance deployment.

---

## New Dependency

Add to `requirements.txt`: `slowapi==0.1.9`

---

## New Files

### `app/core/__init__.py` — empty

### `app/core/rate_limit.py`

**Key function** — extracts user identity for per-user limits:
```python
import jwt
from starlette.requests import Request

def get_rate_limit_key(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            # Decode without verification — just for rate limit keying
            # Actual auth still verified by get_current_user dependency
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload.get("sub", _get_ip(request))
        except Exception:
            pass
    return _get_ip(request)

def _get_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
```

This avoids double Supabase auth verification. Safe because rate limiting is resource protection, not a security boundary.

**Limiter instance:**
```python
import os
from slowapi import Limiter

limiter = Limiter(
    key_func=get_rate_limit_key,
    enabled=os.environ.get("TESTING", "").lower() != "true",
)
```

Disabled in tests via `TESTING=true` env var.

**Rate limit constants:**
```python
LIMIT_HEAVY = "1/day"        # seed pipeline, sync pipeline
LIMIT_IMPORT = "3/hour"      # letterboxd import
LIMIT_REFRESH = "5/hour"     # recommendation refresh (OpenAI)
LIMIT_SEARCH = "30/minute"   # movie search (TMDB per request)
LIMIT_DEFAULT = "60/minute"  # everything else
```

---

## Modified Files

### `main.py` — add slowapi middleware

```python
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.rate_limit import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

### All `views.py` files — add decorators + `request: Request` param

**Important**: slowapi requires `request: Request` as a function parameter on every decorated endpoint. This is the most pervasive change.

Decorator goes after the route decorator (closer to function):
```python
@router.get("/whatever")
@limiter.limit(LIMIT_DEFAULT)
def endpoint(request: Request, ...):
```

**Endpoint → Limit mapping:**

| File | Endpoints | Limit |
|------|-----------|-------|
| `app/import_data/views.py` | `POST /seed-movies` | LIMIT_HEAVY |
| `app/import_data/views.py` | `POST /sync-movies` | LIMIT_HEAVY |
| `app/import_data/views.py` | `POST /letterboxd` | LIMIT_IMPORT |
| `app/movies/views.py` | `GET /search` | LIMIT_SEARCH |
| `app/movies/views.py` | `GET /trending`, `GET /{tmdb_id}` | LIMIT_DEFAULT |
| `app/recommendations/views.py` | `POST /me/refresh` | LIMIT_REFRESH |
| `app/recommendations/views.py` | `GET /me` | LIMIT_DEFAULT |
| `app/tracking/views.py` | all endpoints | LIMIT_DEFAULT |
| `app/watchlist/views.py` | all endpoints | LIMIT_DEFAULT |
| `app/groups/views.py` | all endpoints | LIMIT_DEFAULT |
| `app/auth/views.py` | all endpoints | LIMIT_DEFAULT |
| `app/friends/views.py` | all endpoints | LIMIT_DEFAULT |

---

## Test Compatibility

- `TESTING=true` env var disables all rate limits (set in `tests/conftest.py`)
- If rate limiting needs testing itself, create a separate `tests/test_rate_limit.py` that temporarily enables the limiter and verifies 429 behavior

---

## Future: Scaling to Redis

If the app scales to multiple instances, swap backend with one line:
```python
limiter = Limiter(
    key_func=get_rate_limit_key,
    storage_uri="redis://localhost:6379",
)
```

No other code changes needed.

---

## Verification

1. `.venv/bin/pip install slowapi`
2. `pre-commit run --all-files` — linting passes
3. `uvicorn main:app --reload` — starts clean
4. Hit `GET /movies/search?query=test` 31+ times in 1 minute → 429 on 31st request
5. Hit `POST /import/seed-movies` twice in same day → 429 on 2nd
6. Different JWTs → independent limits
7. With `TESTING=true` → all limits disabled
