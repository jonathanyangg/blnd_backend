import asyncio
import logging

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.analytics import Event, track
from app.core.rate_limit import LIMIT_HEAVY, LIMIT_IMPORT, limiter
from app.dependencies import (
    get_current_user,
    get_db,
    get_tmdb_client,
    openai_client,
    require_admin,
)
from app.auth.models import Profile
from app.import_data import services, workflows
from app.import_data.schemas import (
    ImportNotesRequest,
    ImportNotesResponse,
    ImportSummaryResponse,
    SeedStatusResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/seed-movies",
    response_model=SeedStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(LIMIT_HEAVY)
async def seed_movies(
    request: Request,
    min_popularity: float = Query(default=5.0, ge=1.0),
    user_id: str = Depends(require_admin),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    asyncio.ensure_future(
        services.run_seed_background(tmdb_client, openai_client, min_popularity)
    )
    return {"status": "started", "min_popularity": min_popularity}


@router.post(
    "/sync-movies",
    response_model=SeedStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(LIMIT_HEAVY)
async def sync_movies(
    request: Request,
    user_id: str = Depends(require_admin),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    asyncio.ensure_future(services.run_sync_background(tmdb_client, openai_client))
    return {"status": "started"}


@router.post(
    "/backfill-cast",
    response_model=SeedStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(LIMIT_HEAVY)
async def backfill_cast(
    request: Request,
    user_id: str = Depends(require_admin),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    """Re-fetch all cached movies to backfill cast id + profile_path."""
    asyncio.ensure_future(services.run_backfill_cast_background(tmdb_client))
    return {"status": "started"}


@router.post("/letterboxd", response_model=ImportSummaryResponse)
@limiter.limit(LIMIT_IMPORT)
async def import_letterboxd(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
    content_length: int = Header(default=0, le=workflows.MAX_UPLOAD_SIZE),
):
    file_bytes = await file.read()

    if len(file_bytes) > workflows.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    workflows.validate_zip(file_bytes)

    result = await workflows.run_letterboxd_import(user_id, file_bytes, db, tmdb_client)
    track(
        user_id,
        Event.LETTERBOXD_IMPORTED,
        {"movies_imported": result.imported},
    )
    return result


@router.post("/notes", response_model=ImportNotesResponse)
@limiter.limit(LIMIT_IMPORT)
async def import_notes(
    request: Request,
    body: ImportNotesRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    """Import a free-form movie list (e.g. from Apple Notes) into the watchlist."""
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile or not profile.watchlist_id:
        raise HTTPException(status_code=404, detail="No personal watchlist found")

    result = await workflows.run_notes_import(
        user_id, profile.watchlist_id, body.text, db, tmdb_client
    )
    track(
        user_id,
        Event.NOTES_IMPORTED,
        {
            "movies_added": len(result.added),
            "already_in_watchlist": len(result.already_in_watchlist),
            "unmatched": len(result.unmatched),
        },
    )
    return result
