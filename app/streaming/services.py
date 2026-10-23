import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.streaming.affiliate import apply_amazon_affiliate_tag
from app.streaming.models import StreamingAvailability
from app.movies.models import Movie

logger = logging.getLogger(__name__)

STREAMING_API_BASE = "https://streaming-availability.p.rapidapi.com"
CACHE_TTL_DAYS = 30


def _get_cached(
    tmdb_id: int, country: str, db: Session
) -> StreamingAvailability | None:
    """Return cached entry if it exists and is fresh (< 24h old)."""
    row = (
        db.query(StreamingAvailability)
        .filter(
            StreamingAvailability.tmdb_id == tmdb_id,
            StreamingAvailability.country == country,
        )
        .first()
    )
    if not row:
        return None

    age_days = (
        datetime.now(timezone.utc) - row.fetched_at.replace(tzinfo=timezone.utc)
    ).total_seconds() / 86400
    if age_days > CACHE_TTL_DAYS:
        return None

    return row


def _parse_options(raw_options: list[dict]) -> list[dict]:
    """Parse raw API streaming options into our schema format."""
    results: list[dict] = []
    for opt in raw_options:
        service = opt.get("service", {})
        image_set = service.get("imageSet", {})
        logo_url = image_set.get("darkThemeImage") or image_set.get("lightThemeImage")

        price_raw = opt.get("price")
        price = None
        if price_raw:
            price = {
                "amount": price_raw.get("amount", "0"),
                "currency": price_raw.get("currency", "USD"),
                "formatted": price_raw.get("formatted", ""),
            }

        results.append(
            {
                "service": {
                    "id": service.get("id", ""),
                    "name": service.get("name", ""),
                    "logo_url": logo_url,
                },
                "type": opt.get("type", ""),
                "link": apply_amazon_affiliate_tag(opt.get("link", "")),
                "quality": opt.get("quality"),
                "price": price,
                "expires_soon": opt.get("expiresSoon", False),
            }
        )
    return results


async def fetch_streaming_availability(
    tmdb_id: int, country: str, streaming_client: httpx.AsyncClient
) -> list[dict]:
    """Call the Streaming Availability API for a movie + country."""
    resp = await streaming_client.get(
        f"/shows/movie/{tmdb_id}",
        params={"country": country},
    )
    resp.raise_for_status()
    data = resp.json()

    raw_options = data.get("streamingOptions", {}).get(country, [])
    return raw_options


def _upsert_cache(
    tmdb_id: int, country: str, streaming_data: list[dict], db: Session
) -> None:
    """Insert or update the cache row."""
    existing = (
        db.query(StreamingAvailability)
        .filter(
            StreamingAvailability.tmdb_id == tmdb_id,
            StreamingAvailability.country == country,
        )
        .first()
    )
    if existing:
        existing.streaming_data = streaming_data
        existing.fetched_at = datetime.now(timezone.utc)
    else:
        if db.get(Movie, tmdb_id) is None:
            return
        row = StreamingAvailability(
            tmdb_id=tmdb_id,
            country=country,
            streaming_data=streaming_data,
        )
        db.add(row)
    db.commit()


async def get_streaming_options(
    tmdb_id: int,
    country: str,
    db: Session,
    streaming_client: httpx.AsyncClient,
) -> dict:
    """Cache-through: return cached if fresh, otherwise fetch + cache."""
    cached = _get_cached(tmdb_id, country, db)
    if cached:
        return {
            "tmdb_id": tmdb_id,
            "country": country,
            "options": _parse_options(cached.streaming_data),
        }

    try:
        raw_options = await fetch_streaming_availability(
            tmdb_id, country, streaming_client
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            # Movie not found in API — cache empty result to avoid re-fetching
            raw_options = []
        else:
            raise

    _upsert_cache(tmdb_id, country, raw_options, db)

    return {
        "tmdb_id": tmdb_id,
        "country": country,
        "options": _parse_options(raw_options),
    }
