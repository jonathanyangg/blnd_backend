import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, status

from app.config import settings
from app.database import SessionLocal
from app.dependencies import get_current_user, openai_client
from app.import_data import services

router = APIRouter()
logger = logging.getLogger(__name__)


def _run_seed_pipeline_sync() -> None:
    """Wrapper to run the async pipeline from a sync background task."""
    db = SessionLocal()
    try:
        asyncio.run(
            services.run_seed_pipeline(db, settings.tmdb_api_key, openai_client)
        )
    except Exception:
        logger.exception("Seed pipeline failed")
    finally:
        db.close()


@router.post("/seed-movies", status_code=status.HTTP_202_ACCEPTED)
async def seed_movies(
    background_tasks: BackgroundTasks,
    _user_id: str = Depends(get_current_user),
):
    background_tasks.add_task(_run_seed_pipeline_sync)
    return {"status": "started"}


@router.post("/letterboxd")
async def import_letterboxd():
    return {"imported": 0}
