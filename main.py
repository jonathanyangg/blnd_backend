import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from aioapns import APNs
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from pythonjsonlogger.json import JsonFormatter  # pyright: ignore[reportMissingImports]

from app import analytics
from app.actors.views import router as actors_router
from app.auth.views import router as auth_router
from app.comments.views import router as comments_router
from app.config import settings
from app.core.errors import RequestIdMiddleware, register_exception_handlers
from app.core.rate_limit import limiter
from app.database import engine
from app.friends.views import router as friends_router, user_follows_router
from app.groups.views import router as groups_router
from app.import_data.views import router as import_router
from app.movies.views import router as movies_router
from app.notifications.views import router as notifications_router
from app.recommendations.views import router as recommendations_router
from app.reports.views import router as reports_router
from app.stats.views import router as stats_router
from app.streaming.views import router as streaming_router
from app.subscriptions.views import router as subscriptions_router
from app.tracking.views import router as tracking_router
from app.tv.views import router as tv_router
from app.watchlist.views import router as watchlist_router

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
)
logging.root.handlers = [handler]
logging.root.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    app.state.tmdb_client = httpx.AsyncClient(
        base_url="https://api.themoviedb.org/3",
        headers={"Authorization": f"Bearer {settings.tmdb_api_key}"},
        timeout=30,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    # APNs client -- graceful degradation when not configured
    if settings.apns_key and settings.apns_key_id:
        apns_key = settings.apns_key
        # If it's a file path, read the key content
        if not apns_key.startswith("-----") and Path(apns_key).is_file():
            apns_key = Path(apns_key).read_text()
        app.state.apns_client = APNs(
            key=apns_key,
            key_id=settings.apns_key_id,
            team_id=settings.apple_team_id,
            topic=settings.apple_bundle_id,
            use_sandbox=settings.apns_use_sandbox == "true",
        )
    else:
        app.state.apns_client = None

    app.state.streaming_client = httpx.AsyncClient(
        base_url="https://streaming-availability.p.rapidapi.com",
        headers={
            "X-RapidAPI-Key": settings.rapidapi_key,
            "X-RapidAPI-Host": "streaming-availability.p.rapidapi.com",
        },
        timeout=15,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
    )
    analytics.init()
    yield
    analytics.shutdown()
    await app.state.tmdb_client.aclose()
    await app.state.streaming_client.aclose()
    engine.dispose()


app = FastAPI(title="blnd", version="0.1.0", lifespan=lifespan)

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://blnd.movie",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

app.add_middleware(RequestIdMiddleware)
app.state.limiter = limiter
register_exception_handlers(app)

app.include_router(actors_router, prefix="/actors", tags=["actors"])
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(comments_router, prefix="/comments", tags=["comments"])
app.include_router(movies_router, prefix="/movies", tags=["movies"])
app.include_router(tracking_router, prefix="/tracking", tags=["tracking"])
app.include_router(tv_router, tags=["tv"])
app.include_router(import_router, prefix="/import", tags=["import"])
app.include_router(
    recommendations_router, prefix="/recommendations", tags=["recommendations"]
)
app.include_router(friends_router, prefix="/friends", tags=["friends"])
app.include_router(user_follows_router, prefix="/auth", tags=["follows"])
app.include_router(groups_router, prefix="/groups", tags=["groups"])
app.include_router(watchlist_router, prefix="/watchlist", tags=["watchlist"])
app.include_router(
    notifications_router, prefix="/notifications", tags=["notifications"]
)
app.include_router(streaming_router, prefix="/movies", tags=["streaming"])
app.include_router(reports_router, prefix="/reports", tags=["reports"])
app.include_router(subscriptions_router, tags=["subscriptions"])
app.include_router(stats_router, prefix="/stats", tags=["stats"])


@app.get("/health")
async def health():
    return {"status": "ok"}
