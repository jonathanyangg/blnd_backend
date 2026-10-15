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
from app.import_data.schemas import (
    FilmRecord,
    ImportNotesResponse,
    ImportSummaryResponse,
    NoteCandidate,
    NoteConfirmRequest,
    NoteConfirmResponse,
    NoteLineMatches,
    ParsedTitle,
)
from app.movies.services import get_movie_details
from app.tracking.models import WatchedMovie, WatchlistMovie
from app.tracking.services import add_to_watchlist

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


# --- Notes import ---

MAX_NOTES_TITLES = 100
MAX_NOTE_LINE_LENGTH = 80  # cleaned lines longer than this are likely prose
MAX_PLAUSIBLE_YEAR = 2027  # bare trailing years past this stay in the title

# Leading bullets, numbering ("1." / "1)"), markdown headers, and checklist marks
_LINE_PREFIX_RE = re.compile(r"^(?:[-*•·]+|\d{1,3}[.)]|#+|\[[ xX✓]?\]|[☐☑✅✔✓])\s*")
_EMPHASIS_RE = re.compile(r"\*\*|__|\*")
# ZWJ, misc symbols/dingbats, symbols+arrows, variation selector, SMP pictographs
_EMOJI_RE = re.compile(r"[\u200d\u2600-\u27bf\u2b00-\u2bff\ufe0f\U0001f000-\U0001faff]")
_ANNOTATION_SPLIT_RE = re.compile(r"\s+[-–—]\s+")
_WATCHED_MARKER_RE = re.compile(r"\((?:watched|seen)\)|\b(?:watched|seen)\s*$", re.I)
_PAREN_YEAR_RE = re.compile(r"\(((?:19|20)\d{2})\)")
_BARE_YEAR_RE = re.compile(r"[\s,]+((?:19|20)\d{2})$")


def _clean_note_line(line: str) -> tuple[str, int | None]:
    """Strip note formatting from one line, returning (title, year hint)."""
    s = line
    while match := _LINE_PREFIX_RE.match(s):
        s = s[match.end() :]
    s = _EMPHASIS_RE.sub("", s)
    s = _EMOJI_RE.sub("", s)
    s = _ANNOTATION_SPLIT_RE.split(s, maxsplit=1)[0]
    s = _WATCHED_MARKER_RE.sub("", s).strip()

    year: int | None = None
    if match := _PAREN_YEAR_RE.search(s):
        year = int(match.group(1))
        s = (s[: match.start()] + s[match.end() :]).strip()
    elif match := _BARE_YEAR_RE.search(s):
        candidate = int(match.group(1))
        # "Blade Runner 2049" — a far-future trailing number is part of the title
        if candidate <= MAX_PLAUSIBLE_YEAR and s[: match.start()].strip():
            year = candidate
            s = s[: match.start()]

    s = re.sub(r"\s+", " ", s).strip(" \t,;.")
    return s, year


def parse_note_lines(text: str) -> list[ParsedTitle]:
    """Parse free-form note text into candidate movie titles.

    Strips checklist artifacts, bullets/numbering, markdown emphasis, emoji,
    trailing annotations, and watched markers; extracts year hints. Drops empty
    lines, header-ish lines ending in ":", and prose-length lines.
    """
    parsed: list[ParsedTitle] = []
    for line in text.splitlines():
        raw_line = line.strip()
        if not raw_line:
            continue
        title, year = _clean_note_line(raw_line)
        if not title or title.endswith(":") or len(title) > MAX_NOTE_LINE_LENGTH:
            continue
        parsed.append(ParsedTitle(raw_line=raw_line, title=title, year=year))
    return parsed


def _result_year(item: dict, media_type: str) -> int | None:
    raw = (
        item.get("release_date")
        if media_type == "movie"
        else item.get("first_air_date")
    )
    if not raw:
        return None
    try:
        return int(str(raw)[:4])
    except ValueError:
        return None


def _candidate_confidence(
    query_title: str, query_year: int | None, result_title: str, result_year: int | None
) -> float:
    """Score a TMDB hit. Zero means the title does not match closely enough."""
    if not _title_matches(query_title, result_title):
        return 0.0
    exact = query_title.casefold() == result_title.casefold()
    same_year = query_year is not None and result_year == query_year
    if exact and same_year:
        return 0.97
    if exact and query_year is None:
        return 0.9
    if exact and result_year is not None and abs(result_year - (query_year or 0)) <= 1:
        return 0.75
    if same_year:
        return 0.7
    return 0.55


async def _search_candidates(
    title: str, year: int | None, media_type: str, tmdb_client: httpx.AsyncClient
) -> list[NoteCandidate]:
    path = "/search/movie" if media_type == "movie" else "/search/tv"
    params: dict[str, str] = {"query": title}
    if year is not None:
        key = "primary_release_year" if media_type == "movie" else "first_air_date_year"
        params[key] = str(year)
    response = await tmdb_client.get(path, params=params)
    response.raise_for_status()
    found: list[NoteCandidate] = []
    for item in response.json().get("results", [])[:8]:
        result_title = item.get("title") if media_type == "movie" else item.get("name")
        if not result_title:
            continue
        result_year = _result_year(item, media_type)
        confidence = _candidate_confidence(title, year, result_title, result_year)
        if confidence <= 0:
            continue
        found.append(
            NoteCandidate(
                tmdb_id=item["id"],
                media_type=media_type,
                title=result_title,
                year=result_year,
                poster_path=item.get("poster_path"),
                confidence=confidence,
            )
        )
    return found


async def run_notes_import(
    text: str, tmdb_client: httpx.AsyncClient
) -> ImportNotesResponse:
    """Parse note text and return ranked TMDB candidates. Does not write."""
    from app.config import settings

    parsed = parse_note_lines(text)
    truncated = len(parsed) > MAX_NOTES_TITLES
    parsed = parsed[:MAX_NOTES_TITLES]
    lines: list[NoteLineMatches] = []
    for candidate in parsed:
        matches = await _search_candidates(
            candidate.title, candidate.year, "movie", tmdb_client
        )
        await asyncio.sleep(TMDB_RATE_LIMIT_DELAY)
        if settings.tv_support_enabled:
            matches.extend(
                await _search_candidates(
                    candidate.title, candidate.year, "tv", tmdb_client
                )
            )
            await asyncio.sleep(TMDB_RATE_LIMIT_DELAY)
        matches.sort(key=lambda item: item.confidence, reverse=True)
        lines.append(
            NoteLineMatches(
                raw_line=candidate.raw_line,
                title=candidate.title,
                year=candidate.year,
                candidates=matches[:3],
            )
        )
    return ImportNotesResponse(lines=lines, truncated=truncated)


async def confirm_notes_import(
    user_id: str,
    body: NoteConfirmRequest,
    db: Session,
    tmdb_client: httpx.AsyncClient,
) -> NoteConfirmResponse:
    """Save the titles the user confirmed, to the watchlist or watched list."""
    from app.config import settings
    from app.tv.models import WatchedTVShow
    from app.tv.services import get_tv_show_details

    profile = db.query(Profile).filter(Profile.id == user_id).first()
    added = 0
    skipped = 0
    failed: list[str] = []
    for item in body.items:
        try:
            if item.destination not in ("watchlist", "watched"):
                failed.append(
                    f"{item.tmdb_id}: destination must be watchlist or watched"
                )
                continue
            if item.media_type == "tv":
                if not settings.tv_support_enabled:
                    failed.append(f"{item.tmdb_id}: TV support is disabled")
                    continue
                if item.destination != "watched":
                    failed.append(
                        f"{item.tmdb_id}: TV titles can only be saved as watched"
                    )
                    continue
                await get_tv_show_details(item.tmdb_id, db, tmdb_client)
                exists = (
                    db.query(WatchedTVShow)
                    .filter(
                        WatchedTVShow.user_id == user_id,
                        WatchedTVShow.tmdb_id == item.tmdb_id,
                    )
                    .first()
                )
                if exists:
                    skipped += 1
                    continue
                db.add(
                    WatchedTVShow(
                        user_id=user_id,
                        tmdb_id=item.tmdb_id,
                        rating=item.rating,
                        source="notes_import",
                    )
                )
                added += 1
                continue
            if item.media_type != "movie":
                failed.append(f"{item.tmdb_id}: media_type must be movie or tv")
                continue
            await get_movie_details(item.tmdb_id, db, tmdb_client)
            if item.destination == "watchlist":
                if profile is None or profile.watchlist_id is None:
                    failed.append(f"{item.tmdb_id}: no watchlist")
                    continue
                try:
                    await add_to_watchlist(
                        profile.watchlist_id,
                        item.tmdb_id,
                        user_id,
                        db,
                        tmdb_client,
                        source="notes_import",
                    )
                    added += 1
                except HTTPException as exc:
                    if exc.status_code != 400:
                        raise
                    skipped += 1
                continue
            exists = (
                db.query(WatchedMovie)
                .filter(
                    WatchedMovie.user_id == user_id,
                    WatchedMovie.tmdb_id == item.tmdb_id,
                )
                .first()
            )
            if exists:
                skipped += 1
                continue
            db.add(
                WatchedMovie(
                    user_id=user_id,
                    tmdb_id=item.tmdb_id,
                    rating=item.rating,
                    source="notes_import",
                )
            )
            added += 1
        except Exception:
            db.rollback()
            logger.warning("Notes confirm failed for %s", item.tmdb_id, exc_info=True)
            failed.append(str(item.tmdb_id))
    db.commit()
    return NoteConfirmResponse(added=added, skipped=skipped, failed=failed)
