import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pythonjsonlogger.json import JsonFormatter  # pyright: ignore[reportMissingImports]
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth.views import router as auth_router
from app.config import settings
from app.core.rate_limit import limiter
from app.database import engine
from app.friends.views import router as friends_router
from app.groups.views import router as groups_router
from app.import_data.views import router as import_router
from app.movies.views import router as movies_router
from app.recommendations.views import router as recommendations_router
from app.streaming.views import router as streaming_router
from app.tracking.views import router as tracking_router
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
    app.state.streaming_client = httpx.AsyncClient(
        base_url="https://streaming-availability.p.rapidapi.com",
        headers={
            "X-RapidAPI-Key": settings.rapidapi_key,
            "X-RapidAPI-Host": "streaming-availability.p.rapidapi.com",
        },
        timeout=15,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
    )
    yield
    await app.state.tmdb_client.aclose()
    await app.state.streaming_client.aclose()
    engine.dispose()


app = FastAPI(title="BLND", version="0.1.0", lifespan=lifespan)

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
app.include_router(streaming_router, prefix="/movies", tags=["streaming"])


@app.get("/health")
async def health():
    return {"status": "ok"}
