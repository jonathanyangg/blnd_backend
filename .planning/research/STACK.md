# Stack Research

**Domain:** Letterboxd CSV import pipeline — FastAPI/SQLAlchemy/Supabase Postgres backend
**Researched:** 2026-03-03
**Confidence:** HIGH

---

## Context: What Already Exists

This is a subsequent milestone on an existing backend. The following are already installed and in use — do not re-research or re-install:

| Technology | Installed Version | Role |
|------------|------------------|------|
| FastAPI | 0.135.x (latest) | API framework, file upload endpoint |
| SQLAlchemy | 2.0.46 | ORM, DB session, bulk insert |
| httpx | 0.28.1 (latest) | Async TMDB API client (already wired as `get_tmdb_client` dependency) |
| psycopg2-binary | 2.9.11 | Postgres driver |
| python-multipart | 0.0.22 | Multipart file upload (already in requirements.txt) |
| pydantic | 2.12.5 | Data validation |
| python-dotenv / pydantic-settings | current | Config |

No new runtime dependencies are required for this feature. Every capability needed is already in the installed stack. This is the key finding.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python `zipfile` (stdlib) | 3.11+ built-in | Extract CSVs from Letterboxd zip in-memory | Zero dependencies. `ZipFile.open()` returns a binary file-like object; wrap with `io.TextIOWrapper` for text mode. Never writes to disk. Verified against Python 3.11 docs. |
| Python `csv.DictReader` (stdlib) | 3.11+ built-in | Parse individual CSVs into row dicts | Zero dependencies. Handles quoted fields with commas natively (default `quotechar='"'`). Returns plain `dict` (since Python 3.8+). The Letterboxd CSVs use standard RFC-4180 quoting. |
| `httpx.AsyncClient` (existing) | 0.28.1 | TMDB `/search/movie` calls for name+year resolution | Already installed and wired as `get_tmdb_client` in `dependencies.py`. Use `params={"query": name, "year": year}` — TMDB's `year` parameter is a primary_release_year filter that significantly improves first-result accuracy. |
| SQLAlchemy 2.0 `insert().on_conflict_do_nothing()` (existing) | 2.0.46 | Bulk insert with skip-on-duplicate | The PostgreSQL dialect (`sqlalchemy.dialects.postgresql.insert`) provides `on_conflict_do_nothing()`. This issues a single `INSERT ... ON CONFLICT DO NOTHING` statement per batch, matching the "skip existing entries" requirement without a SELECT-first round trip. |
| FastAPI `UploadFile` (existing) | 0.135.x | Accept the zip file upload at `POST /import/letterboxd` | Already in the stub endpoint. `UploadFile.read()` returns the zip bytes in memory; pass to `io.BytesIO` then `zipfile.ZipFile`. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `io.BytesIO` / `io.TextIOWrapper` (stdlib) | built-in | In-memory zip + CSV text decoding | Always — bridges `UploadFile` bytes → `ZipFile` → `csv.DictReader` without temp files |
| `asyncio.Semaphore` (stdlib) | built-in | Cap concurrent TMDB calls to respect ~40 req/s limit | Use instead of `asyncio-throttle` — stdlib, no install, sufficient for a synchronous-workflow import where calls are sequential per movie anyway |
| `tenacity` | 9.1.4 (latest) | Retry logic for transient TMDB API failures | Only if TMDB returns 429 or 5xx mid-import. Currently NOT installed — add if integration testing reveals flaky behavior under load. Defer until needed. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Supabase CLI (`supabase migration new`) | Raw SQL migrations for `liked` column + `watchlist_movies` table | Already configured. Follow the existing pattern: raw SQL in `supabase/migrations/`, push with `supabase db push` |
| `ruff` + `pyright` (pre-commit) | Linting and type checking | Already configured. Workflow code must pass `pre-commit run --all-files` before commit |

---

## Installation

No new packages are needed. All required capabilities are provided by:
1. Python stdlib (`zipfile`, `csv`, `io`, `asyncio`)
2. Already-installed packages (`httpx`, `SQLAlchemy`, `FastAPI`, `python-multipart`)

```bash
# No new installs required.
# If tenacity is added later for retry logic:
pip install tenacity==9.1.4
# Add to requirements.txt
```

---

## Key Implementation Patterns

### Pattern 1: In-Memory Zip Parsing

```python
import io
import csv
import zipfile
from fastapi import UploadFile

async def parse_letterboxd_zip(file: UploadFile) -> dict[str, list[dict]]:
    raw = await file.read()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        with zf.open("ratings.csv") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
            ratings = list(reader)
    return {"ratings": ratings}
```

**Why:** `io.TextIOWrapper` is required because `ZipFile.open()` returns binary mode. Specifying `encoding="utf-8"` is explicit and safe — Letterboxd exports are UTF-8. The `newline=''` argument is not needed here because `TextIOWrapper` handles it correctly when wrapping a binary stream. Verified against Python 3.11 stdlib docs.

### Pattern 2: TMDB Name+Year Resolution

```python
async def resolve_tmdb_id(
    name: str, year: int, tmdb_client: httpx.AsyncClient
) -> int | None:
    resp = await tmdb_client.get(
        "/search/movie", params={"query": name, "year": year}
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if results:
        return results[0]["id"]
    # Fallback: retry without year filter if year-filtered search returns empty
    resp2 = await tmdb_client.get("/search/movie", params={"query": name})
    resp2.raise_for_status()
    results2 = resp2.json().get("results", [])
    return results2[0]["id"] if results2 else None
```

**Why:** TMDB's `year` parameter (maps to `primary_release_year`) filters results to that release year, making `results[0]` the correct match in nearly all cases. The fallback without `year` handles edge cases where year data is missing or off-by-one (e.g., festival vs. wide release year). The existing TMDB client already handles `api_key` injection via base params in `get_tmdb_client`.

### Pattern 3: Bulk Insert with Skip-on-Duplicate

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.tracking.models import WatchedMovie

def bulk_insert_watched(rows: list[dict], db: Session) -> int:
    if not rows:
        return 0
    stmt = (
        pg_insert(WatchedMovie)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["user_id", "tmdb_id"])
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount
```

**Why:** `on_conflict_do_nothing` maps to `INSERT ... ON CONFLICT (user_id, tmdb_id) DO NOTHING`, which atomically skips existing entries without a SELECT round trip. `watched_movies` already has `unique(user_id, tmdb_id)`, so `index_elements` matches the existing constraint. `rowcount` gives the count of actually-inserted rows for the response summary.

### Pattern 4: TMDB Rate Limiting (Synchronous Workflow)

The workflow is synchronous (no background queue). TMDB allows ~40 req/s. For typical Letterboxd imports (20–200 movies), sequential async calls are fine without explicit throttling — the event loop overhead alone produces ~5-15 ms between awaits. For larger imports (200+ movies), use an `asyncio.Semaphore`:

```python
sem = asyncio.Semaphore(20)  # max 20 concurrent TMDB calls

async def bounded_resolve(name, year, client):
    async with sem:
        return await resolve_tmdb_id(name, year, client)
```

**Do NOT use `asyncio-throttle`** — adds a dependency for a problem stdlib already solves.

---

## CSV Column Map

Verified against the actual Letterboxd export zip at `/Users/adamrose/Desktop/blnd/letterboxd-arose3000-2026-03-04-03-09-utc.zip`:

| File | Columns | Maps To |
|------|---------|---------|
| `ratings.csv` | `Date, Name, Year, Letterboxd URI, Rating` | `watched_movies`: tmdb_id, rating, watched_date |
| `watched.csv` | `Date, Name, Year, Letterboxd URI` | `watched_movies`: tmdb_id, watched_date (no rating) |
| `reviews.csv` | `Date, Name, Year, Letterboxd URI, Rating, Rewatch, Review, Tags, Watched Date` | `watched_movies`: review, rating, watched_date |
| `watchlist.csv` | `Date, Name, Year, Letterboxd URI` | `watchlist_movies`: tmdb_id, added_date |
| `likes/films.csv` | `Date, Name, Year, Letterboxd URI` | `watched_movies.liked = true` |

Key observations:
- `Letterboxd URI` (e.g. `https://boxd.it/2a1m`) is NOT a TMDB ID — resolution via name+year search is required
- `Name` fields can contain commas (e.g. `"Harry Potter and the Philosopher's Stone"`) — `csv.DictReader` handles this with default quoting
- `Rating` in `ratings.csv` is an integer (1-5), not 0.5-step — verify mapping to DB's 0.5-5.0 float scale
- `reviews.csv` uses a separate `Watched Date` column distinct from `Date` (the Letterboxd log date)

---

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| stdlib `csv.DictReader` | `pandas.read_csv()` | Pandas adds ~30MB dependency for reading a 2KB CSV. Letterboxd files are tiny — pandas is complete overkill. No install. |
| stdlib `zipfile` | `python-zipstream`, `zipimport` | stdlib is sufficient and already available |
| `pg_insert().on_conflict_do_nothing()` | Query existing IDs first, filter, then insert | SELECT-first approach requires N+1 queries or a large `WHERE tmdb_id NOT IN (...)` — less efficient and more code. Postgres constraint-based skip is correct. |
| `pg_insert().on_conflict_do_nothing()` | `Session.merge()` per row | `merge()` is an upsert (updates existing rows). The requirement is skip-on-duplicate, not update. |
| `asyncio.Semaphore` | `asyncio-throttle==1.0.2` | `asyncio-throttle` adds a dependency. The stdlib `Semaphore` achieves the same cap on concurrency. For token-bucket rate limiting (req/s), sequential awaits without semaphore are sufficient at typical import sizes. |
| TMDB `/search/movie?year=` | TMDB find-by-external-id (`/find/{id}?external_source=`) | Letterboxd URIs (boxd.it) are not recognized external source IDs by TMDB. Name+year search is the only reliable path. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `pandas` for CSV parsing | Massively oversized dependency (30MB+) for files that are a few KB. Adds install surface, import overhead, and type complexity. | stdlib `csv.DictReader` |
| `aiofiles` for zip reading | The upload bytes are already in memory from FastAPI's `UploadFile.read()`. Async file I/O is only needed for disk reads. | `io.BytesIO` + stdlib `zipfile` |
| `asyncio-throttle` for rate limiting | Last release was 2021 (version 1.0.2), minimal maintenance. Stdlib `asyncio.Semaphore` is sufficient. | `asyncio.Semaphore` (stdlib) |
| `Session.bulk_insert_mappings()` | Deprecated in SQLAlchemy 2.0. Removed/discouraged path. | `session.execute(pg_insert(...).values(...).on_conflict_do_nothing(...))` |
| `Session.execute(insert(...).values(...))` with Core `insert` (not `pg_insert`) | Core `insert` does not have `.on_conflict_do_nothing()`. Must use `sqlalchemy.dialects.postgresql.insert`. | `from sqlalchemy.dialects.postgresql import insert as pg_insert` |
| Temp files for zip extraction | Writing uploaded content to disk creates cleanup complexity, permission issues, and temp-dir races. | In-memory `io.BytesIO` + `ZipFile.open()` |
| Letterboxd URI as a TMDB identifier | `boxd.it` short links do not map to TMDB IDs. TMDB's `/find` endpoint does not recognize them. | TMDB `/search/movie?query=name&year=year` |

---

## Migration Strategy

Two new migrations are required. Follow the existing convention (`supabase migration new <name>` → raw SQL → `supabase db push`):

**Migration 1:** Add `liked` boolean to `watched_movies`
```sql
ALTER TABLE watched_movies ADD COLUMN liked boolean NOT NULL DEFAULT false;
```

**Migration 2:** Create `watchlist_movies` table
```sql
CREATE TABLE watchlist_movies (
    id bigint generated always as identity primary key,
    user_id uuid not null references profiles(id) on delete cascade,
    tmdb_id int not null references movies(tmdb_id),
    added_date date,
    created_at timestamptz default now(),
    unique(user_id, tmdb_id)
);
```

After migrations, update the `WatchedMovie` SQLAlchemy model manually (migrations are source of truth per CLAUDE.md convention).

---

## Version Compatibility

| Package | Version in Use | Compatible With | Notes |
|---------|---------------|-----------------|-------|
| SQLAlchemy | 2.0.46 | psycopg2-binary 2.9.11 | Stable pair; `on_conflict_do_nothing` available since SQLAlchemy 1.4 |
| `sqlalchemy.dialects.postgresql.insert` | part of SQLAlchemy 2.0.46 | Postgres 14+ (Supabase) | `index_elements` must match an existing unique constraint or index |
| Python stdlib `csv` | Python 3.11+ | — | `DictReader` returns `dict` (not `OrderedDict`) since 3.8 |
| Python stdlib `zipfile` | Python 3.11+ | — | `ZipFile.open()` returns binary; `io.TextIOWrapper` required for text CSV parsing |
| FastAPI `UploadFile` | 0.135.x | python-multipart 0.0.22 | `python-multipart` already in requirements.txt; required for multipart form data |

---

## Sources

- Python 3.11 stdlib `csv` docs — `csv.DictReader`, quoting behavior, encoding — HIGH confidence (official docs verified via WebFetch)
- Python 3.11 stdlib `zipfile` docs — `ZipFile.open()`, `io.TextIOWrapper` wrapping pattern — HIGH confidence (official docs verified via WebFetch)
- PyPI `pip3 index versions` — version numbers for sqlalchemy, httpx, fastapi, python-multipart, psycopg2-binary, pydantic, asyncio-throttle, tenacity — HIGH confidence (live PyPI query)
- Codebase inspection — `app/dependencies.py`, `app/movies/services.py`, `app/tracking/models.py`, `app/tracking/services.py`, `app/database.py`, `supabase/migrations/` — HIGH confidence (source of truth)
- Letterboxd export zip at `/Users/adamrose/Desktop/blnd/letterboxd-arose3000-2026-03-04-03-09-utc.zip` — CSV column schemas verified by direct inspection — HIGH confidence
- SQLAlchemy 2.0 `on_conflict_do_nothing` — available via `sqlalchemy.dialects.postgresql.insert` since SQLAlchemy 1.4, stable in 2.0 — HIGH confidence (verified against installed version 2.0.46, confirmed `bulk_insert_mappings` deprecation via SQLAlchemy changelog)
- TMDB `year` search parameter — existing codebase uses `/search/movie` with `query` param; `year` param behavior from TMDB API v3 docs pattern — MEDIUM confidence (WebFetch blocked; based on TMDB API v3 known behavior and existing codebase patterns)

---

*Stack research for: Letterboxd CSV import pipeline (FastAPI/SQLAlchemy/Supabase Postgres)*
*Researched: 2026-03-03*
