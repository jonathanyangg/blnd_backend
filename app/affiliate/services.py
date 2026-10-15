"""TMDB watch-provider cache and affiliate click log."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.affiliate.models import AffiliateClick, WatchProviderCache
from app.affiliate.providers import Offer, Title, links_for
from app.movies.services import get_movie_details
from app.tv.services import get_tv_show_details

logger = logging.getLogger(__name__)

ATTRIBUTION = "Data provided by JustWatch"
CACHE_TTL = timedelta(hours=24)
_KINDS = ("flatrate", "rent", "buy")


def _is_fresh(fetched_at: datetime) -> bool:
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - fetched_at < CACHE_TTL


def _logo(raw: dict) -> str | None:
    logo = raw.get("logo_path")
    return logo if isinstance(logo, str) else None


def _assemble(
    title: Title | None,
    media_type: str,
    tmdb_id: int,
    country: str,
    region: dict,
) -> dict:
    region_link = region.get("link") if isinstance(region.get("link"), str) else None
    fallback = region_link or (
        f"https://www.themoviedb.org/{media_type}/{tmdb_id}/watch"
    )

    def one(kind: str, raw: dict) -> dict | None:
        if not isinstance(raw, dict):
            return None
        provider_id = raw.get("provider_id")
        if not isinstance(provider_id, int):
            return None
        name = raw.get("provider_name") or f"Provider {provider_id}"
        if not isinstance(name, str):
            name = f"Provider {provider_id}"
        if title is None:
            web, app = fallback, None
        else:
            web, app = links_for(
                title,
                Offer(
                    provider_id=provider_id,
                    provider_name=name,
                    monetization=kind,
                    logo_path=_logo(raw),
                    region_link=region_link,
                ),
            )
        return {
            "provider_id": provider_id,
            "provider_name": name,
            "logo_path": _logo(raw),
            "web_url": web,
            "app_url": app,
        }

    grouped: dict[str, list] = {}
    for kind in _KINDS:
        entries = region.get(kind) or []
        if not isinstance(entries, list):
            entries = []
        grouped[kind] = [
            item for item in (one(kind, raw) for raw in entries) if item is not None
        ]

    return {
        "country": country,
        "attribution": ATTRIBUTION,
        "link": region_link,
        "flatrate": grouped["flatrate"],
        "rent": grouped["rent"],
        "buy": grouped["buy"],
    }


def _has_offers(region: dict) -> bool:
    for kind in _KINDS:
        entries = region.get(kind) or []
        if isinstance(entries, list) and entries:
            return True
    return False


async def _load_results(
    media_type: str,
    tmdb_id: int,
    db: Session,
    tmdb_client: httpx.AsyncClient,
) -> dict:
    cached = (
        db.query(WatchProviderCache)
        .filter(
            WatchProviderCache.media_type == media_type,
            WatchProviderCache.tmdb_id == tmdb_id,
        )
        .one_or_none()
    )
    if cached and _is_fresh(cached.fetched_at):
        return cached.results or {}

    try:
        response = await tmdb_client.get(f"/{media_type}/{tmdb_id}/watch/providers")
        response.raise_for_status()
        results = response.json().get("results") or {}
        if not isinstance(results, dict):
            results = {}
    except httpx.HTTPError:
        if cached:
            logger.warning("using stale watch providers for %s %s", media_type, tmdb_id)
            return cached.results or {}
        raise

    now = datetime.now(timezone.utc)
    if cached:
        cached.results = results
        cached.fetched_at = now
        db.commit()
        return results

    db.add(
        WatchProviderCache(
            media_type=media_type,
            tmdb_id=tmdb_id,
            results=results,
            fetched_at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Another request cached this title first.
        db.rollback()
        row = (
            db.query(WatchProviderCache)
            .filter(
                WatchProviderCache.media_type == media_type,
                WatchProviderCache.tmdb_id == tmdb_id,
            )
            .one()
        )
        return row.results or {}
    return results


async def load_title(
    media_type: str,
    tmdb_id: int,
    db: Session,
    tmdb_client: httpx.AsyncClient,
) -> Title:
    """Movie or TV title from the local cache, fetching TMDB on a miss."""
    if media_type == "movie":
        movie = await get_movie_details(tmdb_id, db, tmdb_client)
        return Title(movie.title, movie.year, "movie", movie.tmdb_id)
    show = await get_tv_show_details(tmdb_id, db, tmdb_client)
    return Title(show.title, show.first_air_year, "tv", show.tmdb_id)


async def get_where_to_watch(
    media_type: str,
    tmdb_id: int,
    country: str,
    db: Session,
    tmdb_client: httpx.AsyncClient,
) -> dict | None:
    """Cached TMDB watch offers with affiliate web and app URLs.

    Returns None when TMDB watch providers cannot be loaded. A missing title
    still returns the offers, linked at the JustWatch page.
    """
    region_code = country.upper()
    try:
        results = await _load_results(media_type, tmdb_id, db, tmdb_client)
    except httpx.HTTPError:
        logger.warning("watch providers unavailable for %s %s", media_type, tmdb_id)
        return None

    region = results.get(region_code) or {}
    if not isinstance(region, dict):
        region = {}

    title = None
    if _has_offers(region):
        try:
            title = await load_title(media_type, tmdb_id, db, tmdb_client)
        except httpx.HTTPError:
            logger.warning(
                "title unavailable for %s %s watch links", media_type, tmdb_id
            )
    return _assemble(title, media_type, tmdb_id, region_code, region)


async def load_where_to_watch(
    media_type: str,
    tmdb_id: int,
    country: str,
    db: Session,
    tmdb_client: httpx.AsyncClient,
) -> dict | None:
    """Same as get_where_to_watch, but a failure leaves the caller response intact."""
    try:
        return await get_where_to_watch(media_type, tmdb_id, country, db, tmdb_client)
    except Exception:
        logger.warning(
            "where_to_watch failed for %s %s", media_type, tmdb_id, exc_info=True
        )
        db.rollback()
        return None


def log_click(
    db: Session,
    user_id: str,
    media_type: str,
    tmdb_id: int,
    provider: int,
) -> None:
    """Insert the click and commit. Callers redirect only after this returns."""
    db.add(
        AffiliateClick(
            user_id=uuid.UUID(user_id),
            media_type=media_type,
            tmdb_id=tmdb_id,
            provider=provider,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
