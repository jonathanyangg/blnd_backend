import httpx
from sqlalchemy.orm import Session

from app.movies.models import Movie


async def search_movies(query: str, page: int, tmdb_client: httpx.AsyncClient) -> dict:
    """Search TMDB for movies. No caching — results change over time."""
    response = await tmdb_client.get(
        "/search/movie", params={"query": query, "page": page}
    )
    response.raise_for_status()
    data = response.json()

    results = []
    for item in data.get("results", []):
        year = None
        if item.get("release_date"):
            try:
                year = int(item["release_date"][:4])
            except (ValueError, IndexError):
                pass

        results.append(
            {
                "tmdb_id": item["id"],
                "title": item["title"],
                "year": year,
                "overview": item.get("overview"),
                "poster_path": item.get("poster_path"),
                "genres": [{"id": gid} for gid in item.get("genre_ids", [])],
                "vote_average": item.get("vote_average"),
            }
        )

    return {"results": results, "total_results": data.get("total_results", 0)}


async def get_movie_details(
    tmdb_id: int, db: Session, tmdb_client: httpx.AsyncClient
) -> Movie:
    """Get movie details — returns from DB cache or fetches from TMDB."""
    cached = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
    if cached:
        return cached

    # Fetch movie details and videos in parallel-ish (sequential for simplicity)
    response = await tmdb_client.get(f"/movie/{tmdb_id}")
    response.raise_for_status()
    tmdb_data = response.json()

    # Fetch trailer
    trailer_url = await _fetch_trailer_url(tmdb_id, tmdb_client)

    movie = _cache_movie_from_tmdb(tmdb_data, trailer_url, db)
    return movie


async def _fetch_trailer_url(
    tmdb_id: int, tmdb_client: httpx.AsyncClient
) -> str | None:
    """Fetch the YouTube trailer URL from TMDB videos endpoint."""
    try:
        response = await tmdb_client.get(f"/movie/{tmdb_id}/videos")
        response.raise_for_status()
        videos = response.json().get("results", [])

        for video in videos:
            if video.get("site") == "YouTube" and video.get("type") == "Trailer":
                return f"https://www.youtube.com/watch?v={video['key']}"
    except httpx.HTTPError:
        pass
    return None


def _cache_movie_from_tmdb(
    tmdb_data: dict, trailer_url: str | None, db: Session
) -> Movie:
    """Parse TMDB response into a Movie record and save to DB."""
    year = None
    if tmdb_data.get("release_date"):
        try:
            year = int(tmdb_data["release_date"][:4])
        except (ValueError, IndexError):
            pass

    genres = [{"id": g["id"], "name": g["name"]} for g in tmdb_data.get("genres", [])]

    movie = Movie(
        tmdb_id=tmdb_data["id"],
        title=tmdb_data["title"],
        year=year,
        overview=tmdb_data.get("overview"),
        poster_path=tmdb_data.get("poster_path"),
        genres=genres,
        runtime=tmdb_data.get("runtime"),
        vote_average=tmdb_data.get("vote_average"),
        trailer_url=trailer_url,
    )
    db.add(movie)
    db.commit()
    db.refresh(movie)
    return movie
