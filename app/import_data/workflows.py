import asyncio
import csv
import io
import logging
import re
import zipfile
from datetime import date

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.import_data.schemas import FilmRecord, ImportSummaryResponse
from app.movies.services import get_movie_details
from app.tracking.models import WatchedMovie, WatchlistMovie

logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_DECOMPRESSION_RATIO = 100


def validate_zip(file_bytes: bytes) -> None:
    """Validate that file_bytes is a valid zip archive with safe decompression ratio."""
    if not zipfile.is_zipfile(io.BytesIO(file_bytes)):
        raise HTTPException(status_code=400, detail="File is not a valid zip archive")

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        total_uncompressed = sum(info.file_size for info in zf.infolist())
        if total_uncompressed / len(file_bytes) > MAX_DECOMPRESSION_RATIO:
            raise HTTPException(status_code=400, detail="Zip archive failed validation")


TMDB_RATE_LIMIT_DELAY = 0.025  # ~40 req/s — matches seed pipeline


# Basenames from a Letterboxd export. Anything else in the zip is ignored.
_IMPORT_CSV = {
    "watched.csv": "watched",
    "ratings.csv": "ratings",
    "diary.csv": "diary",
    "reviews.csv": "reviews",
    "watchlist.csv": "watchlist",
}
# likes/ and lists/ are real export folders, but not film history.
_IGNORED_DIRS = {"likes", "lists", "deleted", "__macosx"}


def _csv_members(zf: zipfile.ZipFile) -> dict[str, str]:
    """Map each known CSV to the shallowest safe member in the zip.

    Exports are usually nested in one folder (`letterboxd-user-date/watched.csv`).
    Duplicate names prefer the shorter path. `likes/` and `lists/` never match.
    """
    chosen: dict[str, tuple[int, str]] = {}
    for info in zf.infolist():
        if info.is_dir():
            continue
        parts = [
            part
            for part in info.filename.replace("\\", "/").split("/")
            if part not in ("", ".")
        ]
        if not parts or any(part == ".." for part in parts):
            continue
        if any(part.lower() in _IGNORED_DIRS for part in parts[:-1]):
            continue
        kind = _IMPORT_CSV.get(parts[-1].lower())
        if kind is None:
            continue
        rank = (len(parts), info.filename)
        current = chosen.get(kind)
        if current is None or rank < current:
            chosen[kind] = rank
    return {kind: filename for kind, (_depth, filename) in chosen.items()}


def _rows(zf: zipfile.ZipFile, name: str | None):
    """Yield CSV rows for one zip member. Missing members yield nothing."""
    if not name:
        return
    with zf.open(name) as raw:
        reader = csv.DictReader(
            io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        )
        yield from reader


def _parse_date(value: str | None) -> date | None:
    """Parse a Letterboxd date cell. Blank or junk cells are no date."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _activity_date(row: dict[str, str]) -> date | None:
    """Later of the log date and the watched date, when either is present."""
    logged = _parse_date(row.get("Date"))
    watched = _parse_date(row.get("Watched Date"))
    if logged and watched:
        return max(logged, watched)
    return logged or watched


def _get_or_create(
    merged: dict[str, FilmRecord], row: dict[str, str]
) -> FilmRecord | None:
    """Return the film for this row, creating it when the URI and name exist."""
    uri = (row.get("Letterboxd URI") or "").strip()
    name = (row.get("Name") or "").strip()
    if not uri or not name:
        return None
    if uri not in merged:
        year: int | None = None
        if row.get("Year"):
            try:
                year = int(row["Year"])
            except ValueError:
                year = None
        merged[uri] = FilmRecord(uri=uri, name=name, year=year)
    return merged[uri]


def _apply_rating(record: FilmRecord, row: dict[str, str]) -> None:
    """Keep this row's rating when it is the latest one seen for the film."""
    raw = (row.get("Rating") or "").strip()
    if not raw:
        return
    try:
        rating = float(raw)
    except ValueError:
        return
    rated_on = _activity_date(row)
    current = record.rating_on
    if record.rating is not None:
        if rated_on is None and current is not None:
            return
        if current is not None and rated_on is not None and rated_on < current:
            return
    record.rating = rating
    record.rating_on = rated_on


def _apply_watched_date(record: FilmRecord, row: dict[str, str]) -> None:
    """Keep the latest watch date. A blank cell does not clear one already set."""
    watched_on = _parse_date(row.get("Watched Date")) or _parse_date(row.get("Date"))
    if watched_on is None:
        return
    if record.watched_date is None or watched_on > record.watched_date:
        record.watched_date = watched_on


def _apply_review(record: FilmRecord, row: dict[str, str]) -> None:
    """Keep the latest non-empty review. Older text does not replace it."""
    review = (row.get("Review") or "").strip()
    if not review:
        return
    reviewed_on = _activity_date(row)
    current = record.review_on
    if record.review is not None:
        if reviewed_on is None and current is not None:
            return
        if current is not None and reviewed_on is not None and reviewed_on < current:
            return
    record.review = review
    record.review_on = reviewed_on


def _parse_csvs(file_bytes: bytes) -> dict[str, FilmRecord]:
    """Parse a full Letterboxd export zip into a URI-keyed dict.

    Reads `watched.csv`, `ratings.csv`, `diary.csv`, `reviews.csv`, and
    `watchlist.csv` at the zip root or inside one folder. When the same film
    has more than one rating, the latest date wins. `likes/`, `lists/`, and
    any other file are ignored.
    """
    merged: dict[str, FilmRecord] = {}

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        members = _csv_members(zf)

        for row in _rows(zf, members.get("watched")):
            record = _get_or_create(merged, row)
            if record is None:
                continue
            record.in_watched = True
            _apply_rating(record, row)
            _apply_watched_date(record, row)

        for row in _rows(zf, members.get("ratings")):
            record = _get_or_create(merged, row)
            if record is None:
                continue
            record.in_watched = True
            _apply_rating(record, row)

        for row in _rows(zf, members.get("diary")):
            record = _get_or_create(merged, row)
            if record is None:
                continue
            record.in_watched = True
            _apply_rating(record, row)
            _apply_watched_date(record, row)

        for row in _rows(zf, members.get("reviews")):
            record = _get_or_create(merged, row)
            if record is None:
                continue
            record.in_watched = True
            _apply_rating(record, row)
            _apply_review(record, row)
            _apply_watched_date(record, row)

        for row in _rows(zf, members.get("watchlist")):
            record = _get_or_create(merged, row)
            if record is None:
                continue
            record.in_watchlist = True
            listed_on = _parse_date(row.get("Date"))
            if listed_on is not None and (
                record.watchlist_date is None or listed_on > record.watchlist_date
            ):
                record.watchlist_date = listed_on

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
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    watchlist_id = profile.watchlist_id if profile else None

    merged = _parse_csvs(file_bytes)
    logger.info("Parsed %d unique films from Letterboxd export", len(merged))

    imported = 0
    skipped = 0
    failed = 0
    failed_titles: list[str] = []

    for record in merged.values():
        try:
            tmdb_id = await _resolve_tmdb_id(record.name, record.year, tmdb_client)
            await asyncio.sleep(TMDB_RATE_LIMIT_DELAY)
            if tmdb_id is None:
                logger.warning(
                    "Could not resolve TMDB ID for %s (%s)", record.name, record.year
                )
                failed_titles.append(record.name)
                failed += 1
                continue

            await get_movie_details(tmdb_id, db, tmdb_client)
            await asyncio.sleep(TMDB_RATE_LIMIT_DELAY)

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
                            source="letterboxd_import",
                        )
                    )
                    imported += 1

            if record.in_watchlist and watchlist_id:
                existing_wl = (
                    db.query(WatchlistMovie)
                    .filter(
                        WatchlistMovie.watchlist_id == watchlist_id,
                        WatchlistMovie.tmdb_id == tmdb_id,
                    )
                    .first()
                )
                if not existing_wl:
                    db.add(
                        WatchlistMovie(
                            watchlist_id=watchlist_id,
                            tmdb_id=tmdb_id,
                            added_by=user_id,
                            added_date=record.watchlist_date,
                            source="letterboxd_import",
                        )
                    )
                    imported += 1

        except Exception:
            db.rollback()
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
