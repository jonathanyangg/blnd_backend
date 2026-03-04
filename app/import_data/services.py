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

TMDB_RATE_LIMIT_DELAY = 0.025  # ~40 req/s
FETCH_BATCH_SIZE = 100
EMBED_BATCH_SIZE = 100


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
    # Get IDs already in DB
    existing_ids = {row[0] for row in db.query(Movie.tmdb_id).all()}
    new_ids = [tid for tid in tmdb_ids if tid not in existing_ids]
    logger.info(
        "Fetching %d new movies (%d already cached)", len(new_ids), len(existing_ids)
    )

    fetched = 0
    errors = 0

    async with httpx.AsyncClient(
        base_url="https://api.themoviedb.org/3",
        headers={"Authorization": f"Bearer {tmdb_api_key}"},
    ) as client:
        for i, tmdb_id in enumerate(new_ids):
            try:
                response = await client.get(
                    f"/movie/{tmdb_id}",
                    params={"append_to_response": "credits"},
                )
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                tmdb_data = response.json()

                _cache_movie(tmdb_data, db, commit=False)
                fetched += 1

                # Batch commit
                if fetched % FETCH_BATCH_SIZE == 0:
                    db.commit()

            except Exception:
                errors += 1
                logger.warning("Failed to fetch tmdb_id=%d", tmdb_id, exc_info=True)

            # Rate limit
            await asyncio.sleep(TMDB_RATE_LIMIT_DELAY)

            # Progress log
            if (i + 1) % 500 == 0:
                logger.info("Fetch progress: %d / %d", i + 1, len(new_ids))

    # Final commit
    db.commit()
    logger.info("Fetched %d movies (%d errors)", fetched, errors)
    return {"fetched": fetched, "errors": errors, "skipped": len(existing_ids)}


def embed_movies(db: Session, openai_client: OpenAI) -> dict:
    """Embed movies that have an overview but no embedding yet."""
    # Find movies missing embeddings
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

    embedded = 0
    for i in range(0, len(to_embed), EMBED_BATCH_SIZE):
        batch = to_embed[i : i + EMBED_BATCH_SIZE]
        texts = [
            f"{m.title} ({m.year}): {m.overview}"
            if m.year
            else f"{m.title}: {m.overview}"
            for m in batch
        ]

        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )

        for movie, embedding_data in zip(batch, response.data):
            db.add(
                MovieEmbedding(
                    tmdb_id=movie.tmdb_id,
                    embedding=embedding_data.embedding,
                )
            )

        db.commit()
        embedded += len(batch)
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
    embed_movies(db, openai_client)

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

    movie = Movie(
        tmdb_id=tmdb_data["id"],
        title=tmdb_data["title"],
        year=year,
        overview=tmdb_data.get("overview"),
        poster_path=tmdb_data.get("poster_path"),
        genres=genres,
        runtime=tmdb_data.get("runtime"),
        vote_average=tmdb_data.get("vote_average"),
        trailer_url=None,
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
