import httpx
from sqlalchemy.orm import Session

from app.tv.models import TVShow, WatchedTVShow


def _parse_tv_result(item: dict) -> dict:
    year = None
    if item.get("first_air_date"):
        try:
            year = int(item["first_air_date"][:4])
        except (ValueError, IndexError):
            pass

    return {
        "tmdb_id": item["id"],
        "title": item["name"],
        "year": year,
        "overview": item.get("overview"),
        "poster_path": item.get("poster_path"),
        "vote_average": item.get("vote_average"),
    }


async def search_tv_shows(
    query: str, page: int, tmdb_client: httpx.AsyncClient
) -> dict:
    response = await tmdb_client.get(
        "/search/tv", params={"query": query, "page": page}
    )
    response.raise_for_status()
    data = response.json()

    return {
        "results": [_parse_tv_result(item) for item in data.get("results", [])],
        "total_results": data.get("total_results", 0),
    }


async def get_tv_show_details(
    tmdb_id: int, db: Session, tmdb_client: httpx.AsyncClient
) -> TVShow:
    cached = db.query(TVShow).filter(TVShow.tmdb_id == tmdb_id).first()
    if cached:
        return cached

    response = await tmdb_client.get(f"/tv/{tmdb_id}")
    response.raise_for_status()
    return _cache_tv_show_from_tmdb(response.json(), db)


def _cache_tv_show_from_tmdb(tmdb_data: dict, db: Session) -> TVShow:
    first_air_year = None
    if tmdb_data.get("first_air_date"):
        try:
            first_air_year = int(tmdb_data["first_air_date"][:4])
        except (ValueError, IndexError):
            pass

    episode_run_time = tmdb_data.get("episode_run_time", [])
    show = TVShow(
        tmdb_id=tmdb_data["id"],
        title=tmdb_data["name"],
        first_air_year=first_air_year,
        overview=tmdb_data.get("overview"),
        poster_path=tmdb_data.get("poster_path"),
        backdrop_path=tmdb_data.get("backdrop_path"),
        genres=tmdb_data.get("genres", []),
        number_of_seasons=tmdb_data.get("number_of_seasons"),
        episode_run_time=episode_run_time[0] if episode_run_time else None,
        vote_average=tmdb_data.get("vote_average"),
        vote_count=tmdb_data.get("vote_count"),
    )
    db.add(show)
    db.commit()
    db.refresh(show)
    return show


async def track_tv_show(
    user_id: str,
    tmdb_id: int,
    rating: float | None,
    review: str | None,
    watched_date,
    source: str,
    db: Session,
    tmdb_client: httpx.AsyncClient,
) -> dict:
    show = await get_tv_show_details(tmdb_id, db, tmdb_client)
    existing = (
        db.query(WatchedTVShow)
        .filter(WatchedTVShow.user_id == user_id, WatchedTVShow.tmdb_id == tmdb_id)
        .first()
    )

    if existing:
        if rating is not None:
            existing.rating = rating
        if review is not None:
            existing.review = review
        if watched_date is not None:
            existing.watched_date = watched_date
        entry = existing
    else:
        entry = WatchedTVShow(
            user_id=user_id,
            tmdb_id=tmdb_id,
            rating=rating,
            review=review,
            watched_date=watched_date,
            source=source,
        )
        db.add(entry)

    db.commit()
    db.refresh(entry)
    return _to_response(entry, show)


def _to_response(entry: WatchedTVShow, show: TVShow) -> dict:
    return {
        "id": entry.id,
        "tmdb_id": entry.tmdb_id,
        "title": show.title,
        "rating": entry.rating,
        "review": entry.review,
        "watched_date": entry.watched_date,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }
