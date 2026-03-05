import asyncio
import gzip
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from openai import OpenAI
from sqlalchemy.orm import Session

from app.import_data.models import MovieEmbedding
from app.movies.models import Movie

logger = logging.getLogger(__name__)

FETCH_CONCURRENCY = 20  # max concurrent TMDB requests
MAX_RETRIES = 3
FETCH_BATCH_SIZE = 100
EMBED_BATCH_SIZE = 2000


async def download_tmdb_export(min_popularity: float = 0.0) -> list[int]:
    """Download TMDB daily export and return filtered non-adult movie IDs."""
    # Export is from previous day
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    date_str = yesterday.strftime("%m_%d_%Y")
    url = f"https://files.tmdb.org/p/exports/movie_ids_{date_str}.json.gz"

    logger.info("Downloading TMDB export: %s", url)

    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=120)
        response.raise_for_status()

    tmdb_ids: list[int] = []
    decompressed = gzip.decompress(response.content)
    for line in decompressed.decode("utf-8").strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("adult", False):
            continue
        if entry.get("popularity", 0) < min_popularity:
            continue
        tmdb_ids.append(entry["id"])

    logger.info(
        "Found %d movie IDs from TMDB export (min_popularity=%.1f)",
        len(tmdb_ids),
        min_popularity,
    )
    return tmdb_ids


async def fetch_and_cache_movies(
    tmdb_ids: list[int], db: Session, tmdb_api_key: str
) -> dict:
    """Fetch movie details from TMDB and cache in DB. Skips existing."""
    existing_ids = {row[0] for row in db.query(Movie.tmdb_id).all()}
    new_ids = [tid for tid in tmdb_ids if tid not in existing_ids]
    logger.info(
        "Fetching %d new movies (%d already cached)", len(new_ids), len(existing_ids)
    )

    fetched = 0
    errors = 0
    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def _fetch_one(client: httpx.AsyncClient, tmdb_id: int) -> dict | None:
        async with semaphore:
            for attempt in range(MAX_RETRIES):
                try:
                    response = await client.get(
                        f"/movie/{tmdb_id}",
                        params={"append_to_response": "credits,videos"},
                    )
                    if response.status_code == 404:
                        return None
                    if response.status_code == 429:
                        retry_after = float(response.headers.get("Retry-After", "2"))
                        await asyncio.sleep(retry_after)
                        continue
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError:
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    logger.warning(
                        "Failed to fetch tmdb_id=%d after %d retries",
                        tmdb_id,
                        MAX_RETRIES,
                    )
                    return None
                except Exception:
                    logger.warning("Failed to fetch tmdb_id=%d", tmdb_id, exc_info=True)
                    return None
            return None

    # Process in chunks to batch-commit and log progress
    chunk_size = 500
    async with httpx.AsyncClient(
        base_url="https://api.themoviedb.org/3",
        headers={"Authorization": f"Bearer {tmdb_api_key}"},
        timeout=30,
    ) as client:
        for chunk_start in range(0, len(new_ids), chunk_size):
            chunk = new_ids[chunk_start : chunk_start + chunk_size]
            results = await asyncio.gather(*[_fetch_one(client, tid) for tid in chunk])

            for tmdb_data in results:
                if tmdb_data is not None:
                    try:
                        _cache_movie(tmdb_data, db, commit=False)
                        fetched += 1
                    except Exception:
                        errors += 1
                else:
                    errors += 1

            db.commit()
            logger.info(
                "Fetch progress: %d / %d (fetched=%d, errors=%d)",
                min(chunk_start + chunk_size, len(new_ids)),
                len(new_ids),
                fetched,
                errors,
            )

    logger.info("Fetched %d movies (%d errors)", fetched, errors)
    return {"fetched": fetched, "errors": errors, "skipped": len(existing_ids)}


EMBED_CONCURRENCY = 5


async def embed_movies(db: Session, openai_client: OpenAI) -> dict:
    """Embed movies that have an overview but no embedding yet."""
    existing_embedding_ids = {row[0] for row in db.query(MovieEmbedding.tmdb_id).all()}
    movies = (
        db.query(Movie).filter(Movie.overview.isnot(None), Movie.overview != "").all()
    )
    to_embed = [m for m in movies if m.tmdb_id not in existing_embedding_ids]

    logger.info(
        "Embedding %d movies (%d already have embeddings)",
        len(to_embed),
        len(existing_embedding_ids),
    )

    def _call_openai(texts: list[str]) -> list[list[float]]:
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        return [d.embedding for d in response.data]

    # Build all batches
    batches: list[tuple[list[Movie], list[str]]] = []
    for i in range(0, len(to_embed), EMBED_BATCH_SIZE):
        batch = to_embed[i : i + EMBED_BATCH_SIZE]
        texts = [
            f"{m.title} ({m.year}): {m.overview}"
            if m.year
            else f"{m.title}: {m.overview}"
            for m in batch
        ]
        batches.append((batch, texts))

    # Process in waves of EMBED_CONCURRENCY
    embedded = 0
    for wave_start in range(0, len(batches), EMBED_CONCURRENCY):
        wave = batches[wave_start : wave_start + EMBED_CONCURRENCY]
        results = await asyncio.gather(
            *[asyncio.to_thread(_call_openai, texts) for _, texts in wave]
        )

        for (batch, _), embeddings in zip(wave, results):
            for movie, emb in zip(batch, embeddings):
                db.add(
                    MovieEmbedding(
                        tmdb_id=movie.tmdb_id,
                        embedding=emb,
                    )
                )
            embedded += len(batch)

        db.commit()
        logger.info("Embed progress: %d / %d", embedded, len(to_embed))

    logger.info("Embedded %d movies", embedded)
    return {"embedded": embedded}


async def run_seed_pipeline(
    db: Session,
    tmdb_api_key: str,
    openai_client: OpenAI,
    min_popularity: float = 0.0,
) -> None:
    """Run the full seed pipeline: download → fetch → embed."""
    logger.info("Starting movie seed pipeline (min_popularity=%.1f)", min_popularity)

    tmdb_ids = await download_tmdb_export(min_popularity)
    await fetch_and_cache_movies(tmdb_ids, db, tmdb_api_key)
    await embed_movies(db, openai_client)

    logger.info("Seed pipeline complete")


def _cache_movie(tmdb_data: dict, db: Session, *, commit: bool = True) -> Movie:
    """Parse TMDB response (with appended credits) into a Movie record."""
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
    trailer_url = None
    for video in tmdb_data.get("videos", {}).get("results", []):
        if video.get("site") == "YouTube" and video.get("type") == "Trailer":
            trailer_url = f"https://www.youtube.com/watch?v={video['key']}"
            break

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
    if commit:
        db.commit()
        db.refresh(movie)
    return movie
