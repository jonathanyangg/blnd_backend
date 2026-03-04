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

    # Fetch movie details + credits + videos in one call
    response = await tmdb_client.get(
        f"/movie/{tmdb_id}", params={"append_to_response": "credits,videos"}
    )
    response.raise_for_status()
    tmdb_data = response.json()

    movie = _cache_movie_from_tmdb(tmdb_data, db)
    return movie


def _cache_movie_from_tmdb(tmdb_data: dict, db: Session) -> Movie:
    """Parse TMDB response (with appended credits/videos) into a Movie record."""
    year = None
    if tmdb_data.get("release_date"):
        try:
            year = int(tmdb_data["release_date"][:4])
        except (ValueError, IndexError):
            pass

    genres = [{"id": g["id"], "name": g["name"]} for g in tmdb_data.get("genres", [])]

    # Extract director from credits.crew
    director = None
    credits = tmdb_data.get("credits", {})
    for crew_member in credits.get("crew", []):
        if crew_member.get("job") == "Director":
            director = crew_member["name"]
            break

    # Extract top 5 cast
    cast_list = [
        {"name": c["name"], "character": c.get("character", "")}
        for c in credits.get("cast", [])[:5]
    ]

    # Extract trailer from videos
    trailer_url = _extract_trailer_url(tmdb_data.get("videos", {}))

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
        director=director,
        cast=cast_list,
        tagline=tmdb_data.get("tagline") or None,
        backdrop_path=tmdb_data.get("backdrop_path"),
        imdb_id=tmdb_data.get("imdb_id"),
    )
    db.add(movie)
    db.commit()
    db.refresh(movie)
    return movie


def _extract_trailer_url(videos_data: dict) -> str | None:
    """Extract YouTube trailer URL from TMDB videos response."""
    for video in videos_data.get("results", []):
        if video.get("site") == "YouTube" and video.get("type") == "Trailer":
            return f"https://www.youtube.com/watch?v={video['key']}"
    return None
