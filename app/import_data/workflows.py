import asyncio
import csv
import io
import logging
import re
import zipfile
from datetime import date
from typing import Literal

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.import_data.schemas import (
    FilmRecord,
    ImportNotesResponse,
    ImportSummaryResponse,
    NotesCommitRequest,
    NotesCommitResponse,
    NotesImportItem,
    NotesMovie,
    ParsedTitle,
)
from app.movies.services import get_movie_details
from app.tracking.models import InterestedMovie, WatchedMovie, WatchlistMovie
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


# An exact title (and the same year, when the note gave one) is confident
# enough for the iOS screen to pre-check it. Anything weaker stays a choice.
_HIGH_CONFIDENCE = 0.9


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


def _confidence_label(scores: list[float]) -> Literal["high", "low", "none"]:
    """high pre-checks one movie. low offers a choice. none is a miss."""
    if not scores:
        return "none"
    second = scores[1] if len(scores) > 1 else 0.0
    if scores[0] >= _HIGH_CONFIDENCE and second < _HIGH_CONFIDENCE:
        return "high"
    return "low"


async def _search_movie_candidates(
    title: str, year: int | None, tmdb_client: httpx.AsyncClient
) -> list[tuple[float, NotesMovie]]:
    """Search TMDB movies. A year filter that finds nothing is searched again."""
    params: dict[str, str] = {"query": title}
    if year is not None:
        params["primary_release_year"] = str(year)
    response = await tmdb_client.get("/search/movie", params=params)
    response.raise_for_status()
    found = _scored_movies(title, year, response.json().get("results", []))
    if found or year is None:
        return found
    await asyncio.sleep(TMDB_RATE_LIMIT_DELAY)
    retry = await tmdb_client.get("/search/movie", params={"query": title})
    retry.raise_for_status()
    return _scored_movies(title, year, retry.json().get("results", []))


def _scored_movies(
    title: str, year: int | None, results: list[dict]
) -> list[tuple[float, NotesMovie]]:
    found: list[tuple[float, NotesMovie]] = []
    seen: set[int] = set()
    for item in results[:8]:
        result_title = item.get("title")
        tmdb_id = item.get("id")
        if not result_title or not isinstance(tmdb_id, int) or tmdb_id in seen:
            continue
        result_year = _result_year(item, "movie")
        confidence = _candidate_confidence(title, year, result_title, result_year)
        if confidence <= 0:
            continue
        seen.add(tmdb_id)
        found.append(
            (
                confidence,
                NotesMovie(
                    tmdb_id=tmdb_id,
                    title=result_title,
                    year=result_year,
                    poster_path=item.get("poster_path"),
                ),
            )
        )
    found.sort(key=lambda pair: pair[0], reverse=True)
    return found


async def run_notes_import(
    text: str, tmdb_client: httpx.AsyncClient
) -> ImportNotesResponse:
    """Parse note text and return ranked movie matches. Does not write.

    The iOS screen only decodes movies, so TV search is not used here.
    More than MAX_NOTES_TITLES lines are dropped. One note should not fan
    out into hundreds of TMDB searches.
    """
    parsed = parse_note_lines(text)[:MAX_NOTES_TITLES]
    items: list[NotesImportItem] = []
    for candidate in parsed:
        scored = await _search_movie_candidates(
            candidate.title, candidate.year, tmdb_client
        )
        await asyncio.sleep(TMDB_RATE_LIMIT_DELAY)
        label = _confidence_label([score for score, _movie in scored])
        if label == "none":
            movies: list[NotesMovie] = []
        elif label == "high":
            movies = [scored[0][1]]
        else:
            movies = [movie for _score, movie in scored[:3]]
        items.append(
            NotesImportItem(query=candidate.title, confidence=label, candidates=movies)
        )
    return ImportNotesResponse(items=items)


def _already_saved(model: type, user_id: str, tmdb_id: int, db: Session) -> bool:
    return (
        db.query(model)
        .filter(model.user_id == user_id, model.tmdb_id == tmdb_id)
        .first()
        is not None
    )


async def commit_notes_import(
    user_id: str,
    body: NotesCommitRequest,
    db: Session,
    tmdb_client: httpx.AsyncClient,
) -> NotesCommitResponse:
    """Save every id into one bucket, then return new recommendations.

    `saved` counts rows stored by this call. An id already in that bucket
    is left as it is and is not counted. A TMDB miss is skipped. Either
    way the response is still the commit shape, so a partial save does not
    look like a failure the client would retry.
    """
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    watchlist_id = None if profile is None else profile.watchlist_id
    if body.bucket == "watchlist" and watchlist_id is None:
        raise HTTPException(status_code=404, detail="No watchlist")

    saved = 0
    for tmdb_id in body.tmdb_ids:
        try:
            await get_movie_details(tmdb_id, db, tmdb_client)
            if body.bucket == "watchlist":
                if watchlist_id is None:
                    raise HTTPException(status_code=404, detail="No watchlist")
                try:
                    await add_to_watchlist(
                        watchlist_id,
                        tmdb_id,
                        user_id,
                        db,
                        tmdb_client,
                        source="notes_import",
                    )
                except HTTPException as exc:
                    if exc.status_code != 400:
                        raise
                    continue
            elif body.bucket == "watched":
                if _already_saved(WatchedMovie, user_id, tmdb_id, db):
                    continue
                db.add(
                    WatchedMovie(
                        user_id=user_id, tmdb_id=tmdb_id, source="notes_import"
                    )
                )
                db.commit()
            else:
                if _already_saved(InterestedMovie, user_id, tmdb_id, db):
                    continue
                db.add(
                    InterestedMovie(
                        user_id=user_id, tmdb_id=tmdb_id, source="notes_import"
                    )
                )
                db.commit()
            saved += 1
        except Exception:
            db.rollback()
            logger.warning("Notes commit skipped %s", tmdb_id, exc_info=True)
    return NotesCommitResponse(
        saved=saved,
        recommendations=_notes_recommendations(user_id, body.tmdb_ids, db),
    )


def _notes_recommendations(
    user_id: str, extra_exclude: list[int], db: Session
) -> list[NotesMovie]:
    """Up to eight picks after a save. Empty when the user has no taste yet."""
    from app.recommendations.pipeline import (
        RecommendationContext,
        run_recommendation_pipeline,
    )
    from app.recommendations.services import (
        compute_genre_watch_counts,
        get_hidden_movie_ids,
        get_user_signal_context,
    )

    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if profile is None or profile.taste_embedding is None:
        return []

    watched = [
        row[0]
        for row in db.query(WatchedMovie.tmdb_id)
        .filter(WatchedMovie.user_id == user_id)
        .all()
    ]
    watchlist = (
        [
            row[0]
            for row in db.query(WatchlistMovie.tmdb_id)
            .filter(WatchlistMovie.watchlist_id == profile.watchlist_id)
            .all()
        ]
        if profile.watchlist_id
        else []
    )
    interested = [
        row[0]
        for row in db.query(InterestedMovie.tmdb_id)
        .filter(InterestedMovie.user_id == user_id)
        .all()
    ]
    exclude = list(
        set(
            watched
            + watchlist
            + interested
            + get_hidden_movie_ids(user_id, db)
            + extra_exclude
        )
    )
    user_genres, top_directors, top_cast = get_user_signal_context(
        user_id, db, profile=profile
    )
    genre_counts, total_watches = compute_genre_watch_counts(user_id, db)
    # The integration branch also passes cf_user_ids. This checkout's
    # context does not have that field until that branch is merged.
    extra: dict = {}
    if "cf_user_ids" in RecommendationContext.__dataclass_fields__:
        extra["cf_user_ids"] = [str(user_id)]
    ctx = RecommendationContext(
        positive_embedding=list(profile.taste_embedding),
        negative_embedding=list(profile.negative_embedding)
        if profile.negative_embedding is not None
        else None,
        exclude_ids=exclude,
        user_genres=user_genres,
        top_directors=top_directors,
        top_cast=top_cast,
        genre_watch_counts=genre_counts,
        total_watches=total_watches,
        **extra,
    )
    try:
        results = run_recommendation_pipeline(ctx, db, limit=8, offset=0)
    except Exception:
        logger.warning("Notes recommendations failed", exc_info=True)
        return []
    return [
        NotesMovie(
            tmdb_id=row["tmdb_id"],
            title=row["title"],
            year=row.get("year"),
            poster_path=row.get("poster_path"),
        )
        for row in results
        if row.get("tmdb_id") not in set(extra_exclude)
    ]
