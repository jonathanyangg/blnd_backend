# Phase 2: Core Import Workflow - Research

**Researched:** 2026-03-04
**Domain:** FastAPI file upload, Python stdlib CSV/zipfile, TMDB search API, SQLAlchemy ORM insert patterns
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**TMDB match strategy**
- Use first result from TMDB search (trust TMDB's relevance ranking)
- Search by name + year as provided in CSV
- If zero results: skip the movie and include its title in the "failed" list in the response
- No retry without year — single search attempt per movie
- Basic title verification: confirm the TMDB result title contains at least some words from the Letterboxd title before accepting the match

**Merge & conflict rules**
- Union all CSVs by Letterboxd URI — films appearing in any file are captured
- Ratings in ratings.csv and reviews.csv should always be the same; use whichever is available (no priority needed)
- watched_date: use `Watched Date` from reviews.csv when available, fall back to `Date` from watched.csv
- Liked films not in watched.csv: create a watched_movies entry with liked=true, null rating, null review, null watched_date
- Watchlist entries go to watchlist_movies table (separate from watched_movies)

### Claude's Discretion
- Endpoint contract details (auth requirement, file size limits, content-type handling)
- Import response shape (exact JSON structure for counts and failed titles)
- Internal data structure for the union merge (dict keyed by URI, etc.)
- Order of CSV processing

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CSVP-01 | Endpoint accepts zip file upload at POST /import/letterboxd | FastAPI `UploadFile` + `python-multipart` (already in requirements.txt). Pattern: `async def import_letterboxd(file: UploadFile, ...)`. |
| CSVP-02 | Zip extraction discovers and opens ratings.csv, reviews.csv, watched.csv, watchlist.csv, likes/films.csv | Python stdlib `zipfile.ZipFile(io.BytesIO(await file.read()))` — confirmed working with real export. `zf.namelist()` to verify presence; `zf.open(name)` to read each. |
| CSVP-03 | CSV parsing handles RFC 4180 quoting (commas in movie titles) | Python stdlib `csv.DictReader` handles RFC 4180 natively — confirmed: "The French Dispatch of the Liberty, Kansas Evening Sun" and "O Brother, Where Art Thou?" parse correctly. |
| CSVP-04 | Union merge: all CSVs merged by Letterboxd URI | Dict keyed by URI. Process each CSV and merge fields into per-URI record. 11 films in the real export appear in likes/films.csv but not watched.csv — confirmed real-world need. |
| CSVP-05 | Ratings parsed as floats (0.5-5.0 scale, including half-steps) | `float(row['Rating'])` — confirmed: ratings in CSV are already decimal strings like `'3.5'`, `'4.5'`. Direct float cast works. All values fall in 0.5-5.0 range. |
| CSVP-06 | Reviews parsed with review text and actual `Watched Date` (not `Date` column) | reviews.csv has two date columns: `Date` (log date) and `Watched Date` (actual watch date). Use `row['Watched Date']` for `watched_date`. Confirmed in real export. |
| CSVP-07 | Empty Rating fields in reviews.csv parsed as None, not 0 | Guard: `float(row['Rating']) if row.get('Rating') else None`. The reviews.csv `Rating` field can be empty. |
| TMDB-01 | Each unique movie resolved to a TMDB ID via TMDB search API using name + year | TMDB `/search/movie` accepts `query` + `primary_release_year` params. Use existing `get_tmdb_client` dependency. Returns `results[0]['id']` for first match. |
| TMDB-02 | Resolved movies auto-cached in movies table via existing `get_movie_details` | `app/movies/services.py::get_movie_details(tmdb_id, db, tmdb_client)` fetches TMDB detail + commits to DB. Confirmed: it calls `db.commit()` internally per movie. |
| TMDB-03 | Movies that cannot be resolved are skipped gracefully (not fatal) | Per-movie try/except. Zero results from search → add title to failed list, continue. HTTP error → same treatment. IMPT-05 (per-movie error isolation) is the same concern. |
| IMPT-01 | Watched movies inserted into watched_movies with rating, review, watched_date where available | Create `WatchedMovie` from `app/tracking/models.py`. Fields: user_id, tmdb_id, rating, review, watched_date, liked. |
| IMPT-02 | Existing entries (same user_id + tmdb_id) are skipped, not overwritten | Pattern from codebase: query-first (`db.query(WatchedMovie).filter(...).first()`). If exists → increment skipped counter, do not update. |
| IMPT-03 | Liked films set liked=true; if no watched entry exists, create one with liked=true and null other fields | After processing watched entries, check liked URIs. If URI has a watched entry → set `liked=True` on that object. If not → create new `WatchedMovie(liked=True, rating=None, review=None, watched_date=None)`. |
| IMPT-04 | Watchlist movies inserted into watchlist_movies table | Create `WatchlistMovie` from `app/tracking/models.py`. Fields: user_id, tmdb_id, added_date. Same skip-if-exists pattern. |
| IMPT-05 | Per-movie error isolation — one TMDB failure or DB error does not abort the entire import | Wrap each movie's processing in try/except. On exception: log warning, increment failed count, continue loop. |
| IMPT-06 | Return structured summary: imported count, skipped count, failed count, list of failed movie titles | Response dict: `{"imported": N, "skipped": N, "failed": N, "failed_titles": [...]}`. Define Pydantic schema in `schemas.py`. |
| INFR-01 | All workflow logic in `app/import_data/workflows.py` | File does not yet exist. Create it. Views.py wires stub to workflow function. All parsing + TMDB resolution + DB writes go in workflows.py. |
| INFR-02 | All changes on a feature branch (not main/master) | Already on `arose/letterboxdIntegration`. Confirmed via `git branch`. |
</phase_requirements>

---

## Summary

Phase 2 implements the `POST /import/letterboxd` endpoint end-to-end. The core work spans three layers: (1) zip extraction and CSV parsing using Python's standard library, (2) per-movie TMDB resolution using the existing `get_tmdb_client` dependency and a new TMDB search call, and (3) DB writes using the existing `WatchedMovie` and `WatchlistMovie` models with query-first duplicate detection.

The entire technical stack already exists in the project — `python-multipart` is in `requirements.txt`, `httpx.AsyncClient` for TMDB is available via `get_tmdb_client()`, and `get_movie_details()` handles movie caching. The main new deliverables are: `app/import_data/workflows.py` (union merge + TMDB search + DB writes), an updated `views.py` (wire the stub endpoint), and a new `schemas.py` response schema.

The critical data-confirmed findings from the real Letterboxd export are: (a) 11 of 16 liked films are NOT in watched.csv — confirming the liked-but-not-watched creation path is essential, not an edge case; (b) ratings.csv uses decimal strings like `'3.5'` and `'4.5'` directly compatible with BLND's float scale; (c) Python's `csv.DictReader` handles RFC 4180 quoting correctly for titles with commas.

**Primary recommendation:** Build `workflows.py` as a single async function `run_letterboxd_import(user_id, file_bytes, db, tmdb_client) -> ImportSummary` that: (1) parses all 5 CSVs into a URI-keyed merge dict, (2) resolves each URI to a TMDB ID via search, (3) writes watched/watchlist/liked entries with per-movie error isolation, (4) returns counts. Wire it from `views.py` with `get_current_user`, `get_db`, and `get_tmdb_client` dependencies.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `zipfile` | stdlib | Extract Letterboxd zip in memory | No dependency needed; `ZipFile(io.BytesIO(bytes))` pattern works |
| `csv.DictReader` | stdlib | Parse CSV files with RFC 4180 quoting | Handles quoted commas natively; no third-party lib needed |
| `io.BytesIO` / `io.TextIOWrapper` | stdlib | Bridge bytes → text for CSV reading | Required to wrap zip-opened file for DictReader |
| `fastapi.UploadFile` | FastAPI (current) | Receive zip file upload | Project standard; `python-multipart` already in requirements.txt |
| `httpx.AsyncClient` | existing project dep | TMDB API calls for search + detail | Already used via `get_tmdb_client` dependency; async, same pattern |
| SQLAlchemy ORM | existing project dep | WatchedMovie / WatchlistMovie writes | Project standard; query-first pattern already established in tracking/services.py |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pydantic.BaseModel` | existing project dep | ImportSummary response schema | Define in `import_data/schemas.py`; used in views.py response_model |
| `logging` | stdlib | Per-movie warning on TMDB failure | Already used in services.py; consistent pattern |
| `datetime.date.fromisoformat` | stdlib | Parse date strings from CSV | CSV dates are ISO-8601 format (e.g., `'2024-12-29'`) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Python `csv.DictReader` | `pandas.read_csv` | pandas adds a heavy dependency for a task stdlib handles completely |
| In-memory `io.BytesIO` | Save zip to temp file | Memory approach is simpler; exports are small (this one is <1MB) |
| Query-first duplicate check | Catch `IntegrityError` | Query-first is the existing project pattern; avoids transaction rollback overhead |

**Installation:** No new dependencies needed. All required libraries are already in `requirements.txt`.

---

## Architecture Patterns

### Recommended Project Structure

The phase adds one new file and modifies two existing:

```
app/import_data/
├── __init__.py           # unchanged
├── models.py             # unchanged (MovieEmbedding)
├── schemas.py            # ADD: ImportSummary Pydantic response schema
├── services.py           # unchanged (seed pipeline)
├── views.py              # MODIFY: wire /letterboxd stub to workflow
└── workflows.py          # CREATE: all Letterboxd import logic
```

### Pattern 1: FastAPI File Upload with UploadFile

**What:** Accept a zip file via `multipart/form-data`, read it into bytes, process in memory.
**When to use:** Any endpoint receiving file uploads.

```python
# Source: https://fastapi.tiangolo.com/tutorial/request-files/
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session
import httpx

@router.post("/letterboxd")
async def import_letterboxd(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    file_bytes = await file.read()
    result = await workflows.run_letterboxd_import(user_id, file_bytes, db, tmdb_client)
    return result
```

Note: `python-multipart` is already in `requirements.txt`. No additional install needed.

### Pattern 2: URI-Keyed Union Merge Dict

**What:** Process all 5 CSVs into a single dict keyed by Letterboxd URI so each movie appears only once, with fields populated from whichever CSV(s) contain it.
**When to use:** Any multi-source merge where a key uniquely identifies an entity.

```python
# Internal data structure for the merge
from dataclasses import dataclass, field
from datetime import date

@dataclass
class FilmRecord:
    uri: str
    name: str
    year: int | None
    rating: float | None = None
    review: str | None = None
    watched_date: date | None = None
    in_watched: bool = False
    in_watchlist: bool = False
    watchlist_date: date | None = None
    liked: bool = False
```

Processing order (Claude's discretion — recommended): watched.csv → ratings.csv → reviews.csv → likes/films.csv → watchlist.csv. This lets ratings and reviews overwrite the minimal watched entry rather than vice versa.

### Pattern 3: TMDB Search + Title Verification

**What:** Search TMDB by name + year, take first result, verify the result title contains at least one word from the Letterboxd title.
**When to use:** For each unique URI in the merge dict.

```python
# TMDB search via existing tmdb_client
async def _resolve_tmdb_id(
    name: str,
    year: int | None,
    tmdb_client: httpx.AsyncClient,
) -> int | None:
    params = {"query": name}
    if year:
        params["primary_release_year"] = str(year)
    response = await tmdb_client.get("/search/movie", params=params)
    response.raise_for_status()
    results = response.json().get("results", [])
    if not results:
        return None
    top = results[0]
    # Basic title verification
    if not _title_matches(name, top.get("title", "")):
        return None
    return top["id"]


def _title_matches(lb_title: str, tmdb_title: str) -> bool:
    """Return True if TMDB title shares at least one non-stopword with Letterboxd title."""
    import re
    stopwords = {"the", "a", "an", "of", "in", "to", "and", "or"}
    def words(t):
        return set(re.sub(r"[^\w\s]", "", t.lower()).split()) - stopwords
    lb_words = words(lb_title)
    if not lb_words:
        return True  # degenerate: nothing to check
    return bool(lb_words & words(tmdb_title))
```

**TMDB parameter confirmed:** Use `primary_release_year` (not `year`). Both work, but `primary_release_year` filters only against the primary/canonical release date shown on the TMDB site — more precise for matching Letterboxd's year which reflects the original theatrical release.

### Pattern 4: Query-First Duplicate Detection (Project Standard)

**What:** Before inserting, query to check if the row exists. Skip if it does.
**When to use:** Every insert in the Letterboxd workflow (watched_movies and watchlist_movies both have `UNIQUE(user_id, tmdb_id)`).

```python
# Pattern from app/tracking/services.py — replicate this in workflows.py
existing = (
    db.query(WatchedMovie)
    .filter(WatchedMovie.user_id == user_id, WatchedMovie.tmdb_id == tmdb_id)
    .first()
)
if existing:
    skipped += 1
    # For liked flag: update liked=True on existing if film is liked, per IMPT-03
    if film_record.liked and not existing.liked:
        existing.liked = True
        db.commit()
    continue

entry = WatchedMovie(
    user_id=user_id,
    tmdb_id=tmdb_id,
    rating=film_record.rating,
    review=film_record.review,
    watched_date=film_record.watched_date,
    liked=film_record.liked,
)
db.add(entry)
db.commit()
imported += 1
```

### Pattern 5: Per-Movie Error Isolation

**What:** Wrap each movie's entire processing pipeline in try/except so one failure doesn't abort the import.
**When to use:** Any batch operation over an external API.

```python
for uri, record in merged.items():
    try:
        tmdb_id = await _resolve_tmdb_id(record.name, record.year, tmdb_client)
        if tmdb_id is None:
            failed_titles.append(record.name)
            failed += 1
            continue
        await get_movie_details(tmdb_id, db, tmdb_client)  # cache movie
        # ... insert watched / watchlist entries
    except Exception:
        logger.warning("Failed to import %s (%s)", record.name, record.year, exc_info=True)
        failed_titles.append(record.name)
        failed += 1
```

### Anti-Patterns to Avoid

- **Using `IntegrityError` catch instead of query-first:** The project uses query-first (tracking/services.py). Using `IntegrityError` requires `db.rollback()` and is inconsistent with project style.
- **Calling `db.commit()` inside `get_movie_details`:** `get_movie_details` from `app/movies/services.py` calls `db.commit()` internally when it caches a new movie. This means each TMDB-resolved movie gets its own commit during the caching sub-step. This is acceptable for the import workflow (N commits during TMDB caching is fine vs. the seed pipeline's batch-100 pattern).
- **Processing only watched.csv:** 11 of 16 liked films in the real export do NOT appear in watched.csv. The union merge over all 5 CSVs is mandatory.
- **Treating `Date` from watched.csv as "logging date" instead of watched_date fallback:** Per CONTEXT.md decisions, `Date` from watched.csv IS used as the fallback `watched_date`. It is not ignored.
- **Parsing an empty Rating as 0:** Empty Rating string in reviews.csv must be `None`, not `0.0`. A `0.0` rating is outside the DB check constraint (0.5–5.0).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSV parsing with quoted commas | Custom string splitter | `csv.DictReader` (stdlib) | RFC 4180 quoting is subtle; stdlib handles multi-line quoted fields, escaped quotes, etc. |
| Zip file extraction | Manual byte-range parsing | `zipfile.ZipFile` (stdlib) | Zip format is complex; stdlib is battle-tested |
| Movie detail caching | Duplicate fetch + cache logic | `get_movie_details()` from `app/movies/services.py` | Already handles DB cache check + TMDB fetch + commit |
| TMDB HTTP client lifecycle | Manage httpx.AsyncClient manually | `get_tmdb_client` FastAPI dependency | Already handles auth header injection and proper client open/close |
| JWT auth | Custom token parsing | `get_current_user` dependency | Already implemented; all endpoints require it |

**Key insight:** This phase is almost entirely orchestration of existing primitives. The value is in the workflow logic (merge, resolve, write), not in building new infrastructure.

---

## Common Pitfalls

### Pitfall 1: `get_movie_details` Commits Per Movie
**What goes wrong:** The workflow calls `get_movie_details()` for each resolved movie. Inside that function, `_cache_movie_from_tmdb()` calls `db.commit()` whenever it caches a new movie. This means partial state is committed throughout the import. If the process crashes mid-import, some movies are already in the DB.
**Why it happens:** `get_movie_details` was designed for single-movie on-demand caching, not batch import.
**How to avoid:** This is acceptable for Phase 2. The import workflow already handles duplicates via query-first checks. If `get_movie_details` already committed a movie, a second call will return the cached record (no double-commit). The per-movie try/except ensures DB errors don't cascade.
**Warning signs:** Only a concern if you need true all-or-nothing atomicity. Per requirements (IMPT-05), per-movie error isolation is desired — the current behavior is aligned.

### Pitfall 2: `likes/films.csv` Path Has a Subdirectory
**What goes wrong:** The file is at `likes/films.csv` inside the zip, not `films.csv`. `zf.open('films.csv')` will raise `KeyError`.
**Why it happens:** Letterboxd nests likes files in a subdirectory.
**How to avoid:** Use the full path: `zf.open('likes/films.csv')`. Confirmed from real export: `zf.namelist()` shows `'likes/films.csv'`.
**Warning signs:** `KeyError` when opening the zip entry.

### Pitfall 3: Missing CSV Files Don't Abort the Import
**What goes wrong:** If a Letterboxd account has no reviews, `reviews.csv` may be absent or empty. Opening a missing zip entry raises `KeyError`.
**Why it happens:** Letterboxd exports only include files for data that exists.
**How to avoid:** Check membership before opening: `if 'reviews.csv' in zf.namelist()`. Or wrap each file open in try/except.
**Warning signs:** `KeyError` on `zf.open()`. In the real test export, all 5 target files ARE present, but production exports from minimal accounts may differ.

### Pitfall 4: `Year` Column in CSV Is a String
**What goes wrong:** `row['Year']` is a string like `'2022'`. Passing it directly to TMDB search as a string is fine for the query param, but if converting to `int` for storage/comparison, `int(row['Year'])` is needed.
**Why it happens:** `csv.DictReader` returns all values as strings.
**How to avoid:** `year = int(row['Year']) if row.get('Year') else None`. Also handle potential non-numeric values with try/except.

### Pitfall 5: Title Verification False Negatives on Articles
**What goes wrong:** After stripping stopwords, a short title like "It" or "Us" may have no words left in the comparison set, causing the matcher to always return True. Conversely, a title like "The Matrix" loses "The" and only "matrix" remains — this is fine. The issue is titles where all words are stopwords.
**Why it happens:** Stopword removal is too aggressive for very short titles.
**How to avoid:** If `lb_words` is empty after stopword removal, return `True` (accept the match). This is the "degenerate" case in the code example above. Any non-empty word set must share at least one word with the TMDB result.

### Pitfall 6: `watched_date` Date Parsing
**What goes wrong:** CSV date strings are in `YYYY-MM-DD` format (e.g., `'2024-12-29'`). SQLAlchemy's `Date` column needs a `datetime.date` object, not a string.
**Why it happens:** CSV is string-only.
**How to avoid:** `datetime.date.fromisoformat(date_str)` if the string is non-empty. Guard empty strings: `date.fromisoformat(s) if s else None`.

---

## Code Examples

Verified patterns from project codebase and stdlib:

### Read Zip From UploadFile Bytes
```python
# Source: FastAPI docs + verified with real export
import io
import zipfile

file_bytes = await file.read()
with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
    names = zf.namelist()
    # names includes: 'ratings.csv', 'reviews.csv', 'watched.csv',
    #                  'watchlist.csv', 'likes/films.csv'
```

### Read CSV From Zip Entry
```python
# Source: Python stdlib - confirmed working with real Letterboxd export
import csv
import io

with zf.open('ratings.csv') as raw:
    reader = csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8'))
    for row in reader:
        # row = {'Date': '2024-12-29', 'Name': 'The Matrix',
        #        'Year': '1999', 'Letterboxd URI': 'https://boxd.it/2a1m',
        #        'Rating': '4'}
        name = row['Name']
        year = int(row['Year']) if row.get('Year') else None
        rating = float(row['Rating']) if row.get('Rating') else None
        uri = row['Letterboxd URI']
```

### TMDB Search Call
```python
# Source: existing httpx pattern in app/import_data/services.py + TMDB community docs
response = await tmdb_client.get(
    "/search/movie",
    params={"query": name, "primary_release_year": str(year)},
)
response.raise_for_status()
results = response.json().get("results", [])
# results[0]['id'] is the TMDB ID if len(results) > 0
```

### WatchedMovie Insert (Project ORM Pattern)
```python
# Source: app/tracking/services.py track_movie()
from app.tracking.models import WatchedMovie

entry = WatchedMovie(
    user_id=user_id,   # str UUID from get_current_user
    tmdb_id=tmdb_id,   # int
    rating=rating,     # float | None
    review=review,     # str | None
    watched_date=watched_date,  # datetime.date | None
    liked=liked,       # bool
)
db.add(entry)
db.commit()
```

### WatchlistMovie Insert (Project ORM Pattern)
```python
# Source: app/tracking/models.py WatchlistMovie
from app.tracking.models import WatchlistMovie

entry = WatchlistMovie(
    user_id=user_id,
    tmdb_id=tmdb_id,
    added_date=added_date,  # datetime.date | None
)
db.add(entry)
db.commit()
```

### Query-First Duplicate Skip (Project Standard)
```python
# Source: app/tracking/services.py (replicated pattern)
existing = (
    db.query(WatchedMovie)
    .filter(WatchedMovie.user_id == user_id, WatchedMovie.tmdb_id == tmdb_id)
    .first()
)
if existing:
    skipped += 1
    continue
```

### Pydantic Import Summary Response Schema
```python
# Source: app/tracking/schemas.py patterns + IMPT-06 requirement
from pydantic import BaseModel

class ImportSummaryResponse(BaseModel):
    imported: int
    skipped: int
    failed: int
    failed_titles: list[str]
```

---

## Letterboxd CSV Field Reference

Confirmed from real export (`letterboxd-arose3000-2026-03-04-03-09-utc.zip`):

| File | Columns | Key Fields for This Phase |
|------|---------|--------------------------|
| `ratings.csv` | Date, Name, Year, Letterboxd URI, Rating | URI (key), Name, Year, Rating (float) |
| `reviews.csv` | Date, Name, Year, Letterboxd URI, Rating, Rewatch, Review, Tags, **Watched Date** | URI (key), Rating, Review, **Watched Date** (use this, not Date) |
| `watched.csv` | Date, Name, Year, Letterboxd URI | URI (key), Name, Year, Date (fallback watched_date) |
| `watchlist.csv` | Date, Name, Year, Letterboxd URI | URI (key), Name, Year, Date (→ added_date) |
| `likes/films.csv` | Date, Name, Year, Letterboxd URI | URI (key), Name, Year |

**Row counts in real export:** ratings=46, reviews=1, watched=46, watchlist=8, likes/films=16.
**Liked-but-not-watched count:** 11 films (69% of liked films have no watched entry). This path is essential, not an edge case.

---

## TMDB Parameter Clarification

**`year` vs `primary_release_year`:** Both are valid, functional search parameters. `primary_release_year` filters against only the canonical primary release date; `year` checks all release dates (theatrical + physical + digital). For matching against Letterboxd's year (which reflects theatrical/original release), `primary_release_year` is more precise.

**Recommendation:** Use `primary_release_year`. This is what the TMDB docs show as the recommended year filter for search, and it aligns with Letterboxd's year semantics.

Source: TMDB community documentation (https://www.themoviedb.org/talk/5a87b514c3a3682dbf04eca7)

---

## Endpoint Contract (Claude's Discretion — Recommendation)

- **Auth:** Require JWT via `get_current_user` dependency (consistent with all other endpoints)
- **Content-type:** FastAPI handles `multipart/form-data` automatically with `UploadFile`; no explicit content-type validation needed
- **File size:** No explicit limit for Phase 2 (real Letterboxd exports are <5MB)
- **Response:** HTTP 200 with `ImportSummaryResponse` JSON body
- **Status codes:** 200 on success (even partial), 422 if no file provided (FastAPI auto), 401 if no/invalid JWT

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| `datetime.utcnow()` | `datetime.now(timezone.utc)` | Project convention per CLAUDE.md; utcnow is deprecated in Python 3.12+ |
| Catch `IntegrityError` for duplicates | Query-first before insert | Project pattern in tracking/services.py; avoids transaction rollback |

---

## Open Questions

1. **Missing CSV files in minimal Letterboxd exports**
   - What we know: The real test export contains all 5 target files. Letterboxd documentation does not specify which files are always present.
   - What's unclear: Whether `reviews.csv` or `likes/films.csv` could be absent from an account with no reviews / no liked films.
   - Recommendation: Wrap each `zf.open()` in a try/except `KeyError`, or check `if name in zf.namelist()` before opening. Safe to assume absence means zero records.

2. **`get_movie_details` TMDB API call path**
   - What we know: `get_movie_details` calls TMDB `/movie/{id}?append_to_response=credits,videos`. For the import workflow, we only need the movie cached — the extra credits/videos fetch is slightly wasteful but harmless.
   - What's unclear: Whether to call `get_movie_details` (which fetches full detail including credits/videos) or a lighter internal cache-check + simpler fetch. STATE.md flagged this as a concern.
   - Recommendation: Reuse `get_movie_details` as specified in CONTEXT.md ("The existing `get_movie_details` already handles TMDB fetch + movie caching — reuse it"). The overhead is acceptable for Phase 2 import volumes.

3. **Title verification threshold**
   - What we know: 1-word overlap (after stopword removal) is required per CONTEXT.md. This correctly passes "The French Dispatch..." and "O Brother, Where Art Thou?" and correctly rejects "Spirited Away" vs Japanese title.
   - What's unclear: Whether the 1-word threshold is too lenient for short generic words (e.g., "Up" could match "The Upside").
   - Recommendation: Implement as 1-word overlap with stopword removal as specified. The single-attempt-per-movie decision in CONTEXT.md accepts some false negatives/positives in exchange for simplicity.

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection — `app/import_data/services.py`, `app/movies/services.py`, `app/tracking/services.py`, `app/tracking/models.py`, `app/dependencies.py`, `blnd_backend/CLAUDE.md`
- Real Letterboxd export zip analysis — `letterboxd-arose3000-2026-03-04-03-09-utc.zip` — CSV columns, row counts, edge cases confirmed via Python script
- Python stdlib `zipfile` + `csv.DictReader` — verified correct parsing of zip-nested CSVs with RFC 4180 quoting

### Secondary (MEDIUM confidence)
- FastAPI official docs — https://fastapi.tiangolo.com/tutorial/request-files/ — UploadFile pattern, `python-multipart` requirement, `await file.read()` pattern
- TMDB community docs — https://www.themoviedb.org/talk/5a87b514c3a3682dbf04eca7 — `year` vs `primary_release_year` distinction confirmed

### Tertiary (LOW confidence)
- None — all claims are grounded in codebase inspection or official documentation.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in project; verified from requirements.txt and existing code
- Architecture: HIGH — patterns extracted directly from existing codebase (tracking/services.py, movies/services.py)
- CSV field reference: HIGH — confirmed from real Letterboxd export zip
- TMDB parameter: MEDIUM — confirmed via TMDB community docs, not official API reference page (access was limited)
- Pitfalls: HIGH — most derived from direct code/data inspection

**Research date:** 2026-03-04
**Valid until:** 2026-04-04 (stable stack, stdlib-heavy — low churn risk)
