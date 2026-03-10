import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth.views import router as auth_router
from app.config import settings
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

_origins = (
    [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if settings.cors_origins
    else ["http://localhost:3000"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/health")
async def health():
    return {"status": "ok"}
