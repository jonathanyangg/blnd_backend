import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.dependencies import get_current_user, get_db, get_tmdb_client, openai_client
from app.onboarding import schemas, services

router = APIRouter()


@router.post("/taste", response_model=schemas.OnboardingTasteResponse)
@limiter.limit(LIMIT_DEFAULT)
async def seed_taste(
    request: Request,
    body: schemas.OnboardingTasteRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    """Save 5 or more films as the user's taste and return recommendations."""
    result = await services.seed_onboarding_taste(
        user_id, body, db, tmdb_client, openai_client
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return result
