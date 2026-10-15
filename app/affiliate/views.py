import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.affiliate.providers import REGISTRY, outbound_url
from app.affiliate.services import load_title, log_click
from app.config import settings
from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.dependencies import get_current_user, get_db, get_tmdb_client

router = APIRouter()


@router.get("/out/{provider}/{media_type}/{tmdb_id}")
@limiter.limit(LIMIT_DEFAULT)
async def affiliate_redirect(
    request: Request,
    provider: int,
    media_type: str,
    tmdb_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    """Write the click, then 302 to an allow-listed provider https URL."""
    if media_type not in ("movie", "tv"):
        raise HTTPException(status_code=404, detail="Not found")
    if media_type == "tv" and not settings.tv_support_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if provider not in REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    try:
        title = await load_title(media_type, tmdb_id, db, tmdb_client)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Title not found")
        raise HTTPException(
            status_code=exc.response.status_code, detail="TMDB API error"
        )

    try:
        url = outbound_url(title, provider)
    except ValueError:
        raise HTTPException(status_code=400, detail="Refusing redirect")

    log_click(db, user_id, media_type, tmdb_id, provider)
    return RedirectResponse(url, status_code=302)
