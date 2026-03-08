import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, File, UploadFile, status
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
    min_popularity: float = 5.0,
    _user_id: str = Depends(get_current_user),
):
    asyncio.ensure_future(_run_seed_pipeline_async(min_popularity))
    return {"status": "started", "min_popularity": min_popularity}


@router.post("/letterboxd", response_model=ImportSummaryResponse)
@limiter.limit(LIMIT_IMPORT)
async def import_letterboxd(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    file_bytes = await file.read()
    result = await workflows.run_letterboxd_import(user_id, file_bytes, db, tmdb_client)
    return result
