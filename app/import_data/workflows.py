import csv
import io
import logging
import re
import zipfile
from datetime import date

import httpx
from sqlalchemy.orm import Session

from app.import_data.schemas import ImportSummaryResponse, FilmRecord
from app.movies.services import get_movie_details
from app.tracking.models import WatchedMovie, WatchlistMovie

logger = logging.getLogger(__name__)


def _make_record(row: dict[str, str]) -> FilmRecord:
    """Create a FilmRecord from a CSV row with safe year parsing."""
    year: int | None = None
    if row.get("Year"):
        try:
            year = int(row["Year"])
        except ValueError:
            year = None
    return FilmRecord(uri=row["Letterboxd URI"], name=row["Name"], year=year)


def _get_or_create(merged: dict[str, FilmRecord], row: dict[str, str]) -> FilmRecord:
    """Return existing FilmRecord for URI, or create and register a new one."""
    uri = row["Letterboxd URI"]
    if uri not in merged:
        merged[uri] = _make_record(row)
    return merged[uri]


def _parse_csvs(file_bytes: bytes) -> dict[str, FilmRecord]:
    """Extract and parse all 5 Letterboxd CSVs from the zip into a URI-keyed dict."""
    merged: dict[str, FilmRecord] = {}

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        available = zf.namelist()

        # watched.csv
        if "watched.csv" in available:
            with zf.open("watched.csv") as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))
                for row in reader:
                    record = _get_or_create(merged, row)
                    record.in_watched = True
                    record.watched_date = (
                        date.fromisoformat(row["Date"]) if row.get("Date") else None
                    )

        # ratings.csv
        if "ratings.csv" in available:
            with zf.open("ratings.csv") as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))
                for row in reader:
                    record = _get_or_create(merged, row)
                    record.rating = float(row["Rating"]) if row.get("Rating") else None

        # reviews.csv — rating and watched_date here take priority
        if "reviews.csv" in available:
            with zf.open("reviews.csv") as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))
                for row in reader:
                    record = _get_or_create(merged, row)
                    record.review = row.get("Review") or None
                    record.rating = float(row["Rating"]) if row.get("Rating") else None
                    if row.get("Watched Date"):
                        record.watched_date = date.fromisoformat(row["Watched Date"])

        # likes/films.csv
        if "likes/films.csv" in available:
            with zf.open("likes/films.csv") as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))
                for row in reader:
                    record = _get_or_create(merged, row)
                    record.liked = True

        # watchlist.csv
        if "watchlist.csv" in available:
            with zf.open("watchlist.csv") as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))
                for row in reader:
                    record = _get_or_create(merged, row)
                    record.in_watchlist = True
                    record.watchlist_date = (
                        date.fromisoformat(row["Date"]) if row.get("Date") else None
                    )

    return merged


def _title_matches(lb_title: str, tmdb_title: str) -> bool:
    """Return True if TMDB title shares at least one non-stopword with Letterboxd title."""
    stopwords = {"the", "a", "an", "of", "in", "to", "and", "or"}

    def words(t: str) -> set[str]:
        return set(re.sub(r"[^\w\s]", "", t.lower()).split()) - stopwords

    lb_words = words(lb_title)
    if not lb_words:
        return True
    return bool(lb_words & words(tmdb_title))


async def _resolve_tmdb_id(
    name: str, year: int | None, tmdb_client: httpx.AsyncClient
) -> int | None:
    """Search TMDB for a movie by name + year and return its TMDB ID."""
    params: dict[str, str] = {"query": name}
    if year is not None:
        params["primary_release_year"] = str(year)

    response = await tmdb_client.get("/search/movie", params=params)
    response.raise_for_status()
    results = response.json().get("results", [])

    if not results:
        return None

    top = results[0]
    if not _title_matches(name, top.get("title", "")):
        return None

    return top["id"]


async def run_letterboxd_import(
    user_id: str,
    file_bytes: bytes,
    db: Session,
    tmdb_client: httpx.AsyncClient,
) -> ImportSummaryResponse:
    """Parse a Letterboxd export zip, resolve films, and import to DB."""
    merged = _parse_csvs(file_bytes)
    logger.info("Parsed %d unique films from Letterboxd export", len(merged))

    imported = 0
    skipped = 0
    failed = 0
    failed_titles: list[str] = []

    for record in merged.values():
        try:
            tmdb_id = await _resolve_tmdb_id(record.name, record.year, tmdb_client)
            if tmdb_id is None:
                logger.warning(
                    "Could not resolve TMDB ID for %s (%s)", record.name, record.year
                )
                failed_titles.append(record.name)
                failed += 1
                continue

            await get_movie_details(tmdb_id, db, tmdb_client)

            if record.in_watched or record.liked:
                existing = (
                    db.query(WatchedMovie)
                    .filter(
                        WatchedMovie.user_id == user_id,
                        WatchedMovie.tmdb_id == tmdb_id,
                    )
                    .first()
                )
                if existing:
                    if record.liked and not existing.liked:
                        existing.liked = True
                    skipped += 1
                else:
                    db.add(
                        WatchedMovie(
                            user_id=user_id,
                            tmdb_id=tmdb_id,
                            rating=record.rating,
                            review=record.review,
                            watched_date=record.watched_date,
                            liked=record.liked,
                        )
                    )
                    imported += 1

            if record.in_watchlist:
                existing_wl = (
                    db.query(WatchlistMovie)
                    .filter(
                        WatchlistMovie.user_id == user_id,
                        WatchlistMovie.tmdb_id == tmdb_id,
                    )
                    .first()
                )
                if not existing_wl:
                    db.add(
                        WatchlistMovie(
                            user_id=user_id,
                            tmdb_id=tmdb_id,
                            added_date=record.watchlist_date,
                        )
                    )
                    imported += 1

        except Exception:
            logger.warning(
                "Failed to import %s (%s)", record.name, record.year, exc_info=True
            )
            failed_titles.append(record.name)
            failed += 1
            continue

    db.commit()

    return ImportSummaryResponse(
        imported=imported,
        skipped=skipped,
        failed=failed,
        failed_titles=failed_titles,
    )
