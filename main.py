import json
import logging

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth.views import router as auth_router
from app.core.rate_limit import limiter
from app.friends.views import router as friends_router
from app.groups.views import router as groups_router
from app.import_data.views import router as import_router
from app.movies.views import router as movies_router
from app.recommendations.views import router as recommendations_router
from app.tracking.views import router as tracking_router
from app.watchlist.views import router as watchlist_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="BLND", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(movies_router, prefix="/movies", tags=["movies"])
app.include_router(tracking_router, prefix="/tracking", tags=["tracking"])
app.include_router(import_router, prefix="/import", tags=["import"])
app.include_router(
    recommendations_router, prefix="/recommendations", tags=["recommendations"]
)
app.include_router(friends_router, prefix="/friends", tags=["friends"])
app.include_router(groups_router, prefix="/groups", tags=["groups"])
app.include_router(watchlist_router, prefix="/watchlist", tags=["watchlist"])


_openapi_exported = False


@app.get("/health")
async def health():
    global _openapi_exported
    if not _openapi_exported:
        with open("openapi.json", "w") as f:
            json.dump(app.openapi(), f, indent=2)
        _openapi_exported = True
    return {"status": "ok"}
