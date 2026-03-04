from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, openai_client
from app.recommendations import schemas, services

router = APIRouter()


@router.get("/me", response_model=schemas.RecommendationsResponse)
def get_recommendations(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    return services.get_recommendations(user_id, db, openai_client, limit, offset)


@router.post("/me/refresh", response_model=schemas.RecommendationsResponse)
def refresh_recommendations(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=50),
):
    # Force rebuild taste profile synchronously, then return fresh recs
    services.rebuild_taste_profile(user_id, db, openai_client)
    return services.get_recommendations(user_id, db, openai_client, limit, 0)


@router.get("/group/{group_id}")
async def get_group_recommendations(group_id: int):
    return {"recommendations": []}
