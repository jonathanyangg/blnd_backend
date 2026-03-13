import asyncio
import io
import logging
import zipfile

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

from app.config import settings
from app.core.rate_limit import LIMIT_HEAVY, LIMIT_IMPORT, limiter
from app.database import SessionLocal
from app.dependencies import get_current_user, get_db, get_tmdb_client, openai_client
from app.import_data import services, workflows
from app.import_data.schemas import ImportSummaryResponse

router = APIRouter()
logger = logging.getLogger(__name__)

ADMIN_IDS: set[str] = {settings.admin_user_id} if settings.admin_user_id else set()


def _require_admin(user_id: str) -> None:
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Admin only")


MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_DECOMPRESSION_RATIO = 100


def _validate_zip(file_bytes: bytes) -> None:
    """Validate that file_bytes is a valid zip archive with safe decompression ratio."""
    if not zipfile.is_zipfile(io.BytesIO(file_bytes)):
        raise HTTPException(status_code=400, detail="File is not a valid zip archive")

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        total_uncompressed = sum(info.file_size for info in zf.infolist())
        if total_uncompressed / len(file_bytes) > MAX_DECOMPRESSION_RATIO:
            raise HTTPException(status_code=400, detail="Zip archive failed validation")


async def _run_seed_pipeline_async(min_popularity: float) -> None:
    db = SessionLocal()
    try:
        await services.run_seed_pipeline(
            db, settings.tmdb_api_key, openai_client, min_popularity
        )
    except Exception:
        logger.exception("Seed pipeline failed")
    finally:
        db.close()


@router.post("/seed-movies", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(LIMIT_HEAVY)
async def seed_movies(
    request: Request,
    min_popularity: float = Query(default=5.0, ge=1.0),
    user_id: str = Depends(get_current_user),
):
    _require_admin(user_id)
    asyncio.ensure_future(_run_seed_pipeline_async(min_popularity))
    return {"status": "started", "min_popularity": min_popularity}


async def _run_sync_pipeline_async() -> None:
    db = SessionLocal()
    try:
        await services.run_sync_pipeline(db, settings.tmdb_api_key, openai_client)
    except Exception:
        logger.exception("Sync pipeline failed")
    finally:
        db.close()


@router.post("/sync-movies", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(LIMIT_HEAVY)
async def sync_movies(
    request: Request,
    user_id: str = Depends(get_current_user),
):
    _require_admin(user_id)
    asyncio.ensure_future(_run_sync_pipeline_async())
    return {"status": "started"}


@router.post("/letterboxd", response_model=ImportSummaryResponse)
@limiter.limit(LIMIT_IMPORT)
async def import_letterboxd(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
    content_length: int = Header(default=0, le=MAX_UPLOAD_SIZE),
):
    file_bytes = await file.read()

    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    _validate_zip(file_bytes)

    result = await workflows.run_letterboxd_import(user_id, file_bytes, db, tmdb_client)
    return result
