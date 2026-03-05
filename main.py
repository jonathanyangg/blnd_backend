import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth.views import router as auth_router
from app.movies.views import router as movies_router
from app.tracking.views import router as tracking_router
from app.import_data.views import router as import_router
from app.recommendations.views import router as recommendations_router
from app.friends.views import router as friends_router
from app.groups.views import router as groups_router
from app.watchlist.views import router as watchlist_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    with open("openapi.json", "w") as f:
        json.dump(_app.openapi(), f, indent=2)
    yield


app = FastAPI(title="BLND", version="0.1.0", lifespan=lifespan)

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
