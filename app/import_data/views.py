import asyncio
import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.dependencies import get_current_user, get_db, get_tmdb_client, openai_client
from app.import_data import services, workflows
from app.import_data.schemas import ImportSummaryResponse

router = APIRouter()
logger = logging.getLogger(__name__)


def _run_seed_pipeline_sync(min_popularity: float) -> None:
    """Wrapper to run the async pipeline from a sync background task."""
    db = SessionLocal()
    try:
        asyncio.run(
            services.run_seed_pipeline(
                db, settings.tmdb_api_key, openai_client, min_popularity
            )
        )
    except Exception:
        logger.exception("Seed pipeline failed")
    finally:
        db.close()


@router.post("/seed-movies", status_code=status.HTTP_202_ACCEPTED)
async def seed_movies(
    background_tasks: BackgroundTasks,
    min_popularity: float = 5.0,
    _user_id: str = Depends(get_current_user),
):
    background_tasks.add_task(_run_seed_pipeline_sync, min_popularity)
    return {"status": "started", "min_popularity": min_popularity}


@router.post("/letterboxd", response_model=ImportSummaryResponse)
async def import_letterboxd(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    file_bytes = await file.read()
    result = await workflows.run_letterboxd_import(user_id, file_bytes, db, tmdb_client)
    return result
