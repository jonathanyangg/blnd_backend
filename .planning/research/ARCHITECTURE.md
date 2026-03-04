# Architecture Research

**Domain:** Letterboxd CSV import workflow — FastAPI + SQLAlchemy + TMDB backend
**Researched:** 2026-03-03
**Confidence:** HIGH (based on direct codebase inspection + stdlib knowledge)

## Standard Architecture

### System Overview

```
POST /import/letterboxd
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│                    views.py (HTTP layer)                     │
│  Receives: UploadFile (zip), user_id from JWT               │
│  Returns: ImportResultResponse                              │
└──────────────────────────┬──────────────────────────────────┘
                           │ calls
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                 workflows.py (orchestrator)                  │
│  run_letterboxd_import(file_bytes, user_id, db, tmdb)       │
│                                                             │
│  1. extract_csvs(zip_bytes)  →  ParsedCSVs dataclass       │
│  2. resolve_tmdb_ids(rows, tmdb_client) → {name+year: int} │
│  3. ensure_movies_cached(tmdb_ids, db, tmdb_client)        │
│  4. insert_watched(rows, tmdb_map, user_id, db)            │
│  5. insert_watchlist(rows, tmdb_map, user_id, db)          │
│  6. apply_likes(like_rows, tmdb_map, user_id, db)          │
└──────────────────────────┬──────────────────────────────────┘
                           │ calls
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐
│  zipfile     │  │  TMDB API    │  │  SQLAlchemy / DB     │
│  (stdlib)    │  │  (httpx)     │  │  watched_movies      │
│  csv         │  │  /search/    │  │  watchlist_movies    │
│  (stdlib)    │  │  movie?q=..  │  │  movies (FK cache)   │
└──────────────┘  └──────────────┘  └──────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|----------------|----------------|
| `views.py` | HTTP endpoint, file receive, dependency injection, response shaping | FastAPI `UploadFile`, calls `workflows.py` |
| `workflows.py` | Top-level orchestration — ties all steps together, returns summary | Single `async def run_letterboxd_import(...)` |
| ZIP extractor | Open zip bytes in-memory, read named CSV files, decode UTF-8 | `zipfile.ZipFile(io.BytesIO(bytes))` |
| CSV parser | Parse each CSV into typed row dicts; handle quoted commas in titles | `csv.DictReader(io.StringIO(text))` |
| TMDB resolver | Search TMDB by `Name + Year`, return first-result TMDB ID; cache results in a local dict to avoid duplicate API calls | `movies.services.search_movies` or direct `/search/movie` |
| Movie cacher | Ensure each resolved TMDB ID exists in `movies` table (FK constraint) | `movies.services.get_movie_details` (already handles cache-or-fetch) |
| DB inserter — watched | Bulk-skip-insert `watched_movies` rows; skip if `(user_id, tmdb_id)` already exists | SQLAlchemy INSERT ... ON CONFLICT DO NOTHING via `execute()` |
| DB inserter — watchlist | Bulk-skip-insert `watchlist_movies` rows (new table needed) | Same conflict-skip pattern |
| Like applier | SET `liked=true` on existing `watched_movies` rows that match liked films | SQLAlchemy UPDATE WHERE IN |

## Recommended Project Structure

The workflow lives entirely inside the existing `app/import_data/` domain — no new top-level folders needed.

```
app/import_data/
├── __init__.py
├── views.py        # HTTP endpoint — receives zip, calls workflow, returns summary
├── schemas.py      # Pydantic: ImportResultResponse (counts of imported rows per type)
└── workflows.py    # All logic: extraction → parsing → TMDB resolution → DB writes
```

All DB table additions (migration files) go in the existing location:

```
supabase/migrations/
├── 20260302052101_initial_schema.sql          (existing)
├── 20260302053704_add_taste_profile_to_profiles.sql  (existing)
├── 20260303034025_add_trailer_url_to_movies.sql      (existing)
├── YYYYMMDDHHMMSS_add_liked_to_watched_movies.sql    (new — adds `liked` boolean)
└── YYYYMMDDHHMMSS_create_watchlist_movies.sql        (new — creates watchlist_movies table)
```

### Structure Rationale

- **workflows.py only:** PROJECT.md explicitly requires all logic in `app/import_data/workflows.py`. The existing codebase uses `workflows.py` for multi-step orchestration (same convention as `recommendations/` and `groups/`).
- **No `services.py` for import_data:** Unlike the other domains, import is a single workflow not a set of reusable service functions. Keep everything in `workflows.py` unless it grows significantly.
- **Reuse `movies.services.get_movie_details`:** This function already handles cache-or-fetch-from-TMDB and respects the FK constraint on `movies`. Do not duplicate it.

## Architectural Patterns

### Pattern 1: In-Memory Zip Extraction

**What:** Read the uploaded file bytes entirely into memory, then open with `zipfile.ZipFile(io.BytesIO(content))`. Extract only the specific named files needed; ignore everything else.

**When to use:** Always for this feature. Letterboxd exports are small (< 1 MB for typical users). Temp files on disk add complexity with no benefit.

**Trade-offs:** Simplest approach; works for any file size a user would realistically have. Would only be a concern at 100MB+ which is not a Letterboxd export scenario.

**Example:**
```python
import io
import zipfile
import csv

async def extract_csvs(file_bytes: bytes) -> dict[str, list[dict]]:
    result = {}
    target_files = {
        "ratings.csv",
        "reviews.csv",
        "watched.csv",
        "watchlist.csv",
        "likes/films.csv",
    }
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        available = set(z.namelist())
        for name in target_files:
            if name not in available:
                result[name] = []
                continue
            text = z.read(name).decode("utf-8")
            reader = csv.DictReader(io.StringIO(text))
            result[name] = list(reader)
    return result
```

### Pattern 2: TMDB Resolution with Local Cache Dict

**What:** For each CSV row, construct a `(Name, Year)` key. Before calling TMDB, check an in-memory dict built during this import run. Return the first TMDB search result's ID. If no match found, log and skip the row — do not error.

**When to use:** Always. A single import may reference hundreds of movies. Without deduplication, `ratings.csv` and `watched.csv` share all the same movies, causing 2x TMDB API calls for every film.

**Trade-offs:** A user with 500 watched films triggers 500 TMDB search requests. At TMDB's ~40 req/s limit, this takes ~12.5 seconds synchronously. Acceptable for v1. Rate limiting with `asyncio.sleep` between batches is the mitigation if needed.

**Example:**
```python
async def resolve_tmdb_ids(
    rows: list[dict],
    tmdb_client: httpx.AsyncClient,
    tmdb_map: dict[tuple, int],  # mutable, shared across all CSV files
) -> None:
    """Resolve Name+Year → TMDB ID for rows not already in tmdb_map."""
    for row in rows:
        key = (row["Name"], row.get("Year", ""))
        if key in tmdb_map:
            continue
        query = f"{row['Name']} {row.get('Year', '')}".strip()
        try:
            response = await tmdb_client.get(
                "/search/movie", params={"query": query, "page": 1}
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            if results:
                tmdb_map[key] = results[0]["id"]
        except httpx.HTTPError:
            pass  # Skip unresolvable rows
```

### Pattern 3: INSERT ... ON CONFLICT DO NOTHING for Bulk Skip-Insert

**What:** Use SQLAlchemy Core's `insert()` with PostgreSQL's `on_conflict_do_nothing()` to bulk-insert rows while silently skipping any that would violate the `unique(user_id, tmdb_id)` constraint.

**When to use:** For `watched_movies` and `watchlist_movies` bulk inserts. This is more efficient than a Python-level "check if exists, then insert" loop, which would require N SELECT queries before N INSERT queries.

**Trade-offs:** Requires SQLAlchemy Core (not ORM) for the conflict clause. Slightly less readable than ORM pattern but substantially more efficient for batches of 100+ rows.

**Example:**
```python
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.tracking.models import WatchedMovie

def bulk_insert_watched(
    rows: list[dict],  # pre-filtered: only rows with resolved tmdb_ids
    user_id: str,
    db: Session,
) -> int:
    if not rows:
        return 0
    stmt = pg_insert(WatchedMovie).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "tmdb_id"])
    result = db.execute(stmt)
    db.commit()
    return result.rowcount
```

### Pattern 4: Separate Resolution from Insertion (Two-Pass)

**What:** First pass — resolve all rows from all CSVs to TMDB IDs and cache all movies. Second pass — do all DB inserts. Never interleave TMDB API calls with DB transactions.

**When to use:** Always. Keeps the TMDB-network phase and the DB-write phase cleanly separated. A TMDB failure doesn't leave a partial DB transaction. A DB failure doesn't cause extra TMDB calls.

**Trade-offs:** Slightly more memory (hold all resolved rows in-memory before writing). For a typical Letterboxd export this is negligible.

## Data Flow

### Full Import Flow

```
Client
  │  POST /import/letterboxd
  │  Content-Type: multipart/form-data
  │  Body: file=<zip bytes>
  ▼
views.py
  │  file.read() → bytes
  │  user_id from get_current_user()
  │
  ▼
workflows.py: run_letterboxd_import(zip_bytes, user_id, db, tmdb_client)
  │
  ├─ Step 1: extract_csvs(zip_bytes)
  │    zipfile.ZipFile(io.BytesIO)
  │    csv.DictReader per file
  │    → ParsedRows{watched, ratings, reviews, watchlist, likes}
  │
  ├─ Step 2: resolve_tmdb_ids(all_rows, tmdb_client, tmdb_map={})
  │    For each unique (Name, Year) across all CSVs:
  │      GET /search/movie?query=...
  │      → tmdb_map[(Name, Year)] = tmdb_id
  │
  ├─ Step 3: ensure_movies_cached(unique_tmdb_ids, db, tmdb_client)
  │    For each resolved tmdb_id:
  │      movies.services.get_movie_details(tmdb_id, db, tmdb_client)
  │      → movie row exists in `movies` table (satisfies FK)
  │
  ├─ Step 4: bulk_insert_watched(watched+ratings+reviews rows, user_id, db)
  │    Merge data: watched.csv provides base, ratings.csv adds rating,
  │    reviews.csv adds review text + watched_date
  │    INSERT INTO watched_movies ON CONFLICT DO NOTHING
  │    → watched_count (number of new rows inserted)
  │
  ├─ Step 5: bulk_insert_watchlist(watchlist rows, user_id, db)
  │    INSERT INTO watchlist_movies ON CONFLICT DO NOTHING
  │    → watchlist_count
  │
  └─ Step 6: apply_likes(like_rows, tmdb_map, user_id, db)
       UPDATE watched_movies SET liked=true
       WHERE user_id=? AND tmdb_id IN (resolved like tmdb_ids)
       → liked_count (rows updated)
  │
  ▼
views.py returns ImportResultResponse:
  {
    "watched_imported": 47,
    "watchlist_imported": 12,
    "liked_applied": 8,
    "skipped": 3,   # rows where TMDB resolution failed
  }
```

### CSV Merge Strategy (Watched + Ratings + Reviews)

The three CSVs all represent watched movies but carry different fields. Merge them by `(Name, Year)` key before inserting:

```
watched.csv    → provides: Name, Year, Letterboxd URI (base "watched" fact)
ratings.csv    → provides: Rating (0.5–5.0 half-star scale)
reviews.csv    → provides: Rating, Review text, Tags, Watched Date, Rewatch flag
```

Build a single merged dict keyed by `(Name, Year)`. `reviews.csv` has the richest data per row; treat it as the highest-priority source. `ratings.csv` fills in rating where no review exists. `watched.csv` covers everything else (films logged without rating or review).

### Data Flow for Liked Films

Likes require special handling: `likes/films.csv` entries may or may not be in `watched.csv`. The safest approach:

```
likes/films.csv rows
  │
  ▼ resolve tmdb_ids (same tmdb_map — no extra API calls if already watched)
  │
  ▼ UPDATE watched_movies SET liked=true
    WHERE user_id=:uid AND tmdb_id IN (:ids)
    -- only updates rows that exist; silently skips liked-but-not-watched films
    -- (a film can be liked on Letterboxd without being marked watched)
```

Do not INSERT a watched_movies row just because a film is liked — that would create phantom watched entries.

## Build Order

Dependencies between components drive this sequencing:

```
1. Migrations (no dependencies)
   ├── Add `liked` boolean to watched_movies
   └── Create watchlist_movies table

2. schemas.py (no code dependencies, just Pydantic types)
   └── ImportResultResponse

3. ZIP extractor + CSV parser (pure stdlib, no DB/TMDB dependencies)
   └── extract_csvs() function in workflows.py

4. TMDB resolver (depends on: httpx client from dependencies.py)
   └── resolve_tmdb_ids() in workflows.py
   └── Reuses: movies.services.search_movies (or direct tmdb_client call)

5. Movie cacher (depends on: DB session + TMDB client)
   └── Reuses: movies.services.get_movie_details (already exists — no new code)

6. DB inserters (depends on: migrations from step 1, Movie rows from step 5)
   ├── bulk_insert_watched()
   ├── bulk_insert_watchlist()
   └── apply_likes()

7. Workflow orchestrator (depends on: all above)
   └── run_letterboxd_import() in workflows.py

8. views.py endpoint (depends on: workflow from step 7, schemas from step 2)
   └── POST /import/letterboxd with UploadFile + auth
```

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0-500 watched films | Synchronous is fine. Single import takes 5-15s (TMDB rate limit is the bottleneck). Return result directly in HTTP response. |
| 500-2000 films | Add `asyncio.sleep(0.025)` between TMDB batches to stay under 40 req/s. Still synchronous — HTTP timeout becomes a risk (FastAPI default is no timeout, so client timeout is what matters). |
| 2000+ films | Move to background task: return 202 Accepted + job ID immediately, poll for result. Requires a jobs table or Redis. Out of scope for v1. |

### Scaling Priorities

1. **First bottleneck — TMDB rate limit:** 40 requests/second. A 500-film import needs 500 search calls + 500 detail calls = 1000 TMDB calls = ~25 seconds. Deduplicate aggressively (the shared `tmdb_map` dict handles this). For detail calls, the existing `get_movie_details` cache-check means repeat runs of the same import are much faster.
2. **Second bottleneck — synchronous HTTP response timeout:** At 2000+ films, the import takes minutes. The client will likely timeout before the server finishes. Mitigation: background task with polling. Not needed for v1.

## Anti-Patterns

### Anti-Pattern 1: Row-by-Row DB Existence Checks

**What people do:** For each CSV row, query `SELECT 1 FROM watched_movies WHERE user_id=? AND tmdb_id=?` in Python, then conditionally INSERT.

**Why it's wrong:** 500 films = 500 SELECT queries + up to 500 INSERT queries = 1000 round trips to the DB. `ON CONFLICT DO NOTHING` does this in a single statement.

**Do this instead:** Build the full list of rows to insert in Python, then issue one `INSERT ... ON CONFLICT DO NOTHING` statement with all rows.

### Anti-Pattern 2: Interleaving TMDB Calls with DB Transactions

**What people do:** For each row: resolve TMDB ID → open DB transaction → INSERT → commit. Repeat.

**Why it's wrong:** TMDB network latency (100-300ms per call) holds open DB transactions needlessly. A TMDB failure mid-loop leaves partial state. N separate commits instead of one.

**Do this instead:** Two clean phases — (1) all TMDB resolution, (2) all DB writes. No open DB sessions during TMDB calls.

### Anti-Pattern 3: Creating Watched Entries for Liked-Only Films

**What people do:** See a film in `likes/films.csv`, INSERT it into `watched_movies` to set `liked=true`.

**Why it's wrong:** Letterboxd allows liking a film without having watched it. This would create false "watched" entries that corrupt the user's watch history and mess up recommendation signals.

**Do this instead:** `UPDATE watched_movies SET liked=true WHERE user_id=? AND tmdb_id IN (?)`. Only updates films the user has actually watched.

### Anti-Pattern 4: Stopping the Import on Any TMDB Failure

**What people do:** If `GET /search/movie` returns a non-200 or empty results for one film, raise an exception and abort.

**Why it's wrong:** Obscure film titles, foreign films, or short-lived TMDB outages will cause the entire import to fail when 499/500 films resolved fine.

**Do this instead:** Skip unresolvable rows, count them, and return the count in the response as `"skipped": N`. The user can see what didn't import.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| TMDB `/search/movie` | Async httpx via existing `get_tmdb_client` dependency | Use `query="{Name} {Year}"` — Year significantly reduces false positives for remakes/series |
| TMDB `/movie/{id}` | Via existing `movies.services.get_movie_details` — no new code | Already handles DB cache-or-fetch + FK constraint satisfaction |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `views.py` → `workflows.py` | Direct async function call | `views.py` passes `file.read()` bytes + injected dependencies |
| `workflows.py` → `movies.services` | Direct function call (same process) | Reuse `get_movie_details` — do not duplicate movie caching logic |
| `workflows.py` → DB | SQLAlchemy Session passed as dependency | Use Core `insert()` for bulk ops, ORM for single-row queries |
| `workflows.py` → TMDB | httpx.AsyncClient passed as dependency | Same client instance that all other endpoints use |

### New DB Tables Required

Both tables must exist before the workflow can run. Create via Supabase migrations (raw SQL):

**Migration 1: `liked` column on `watched_movies`**
```sql
alter table watched_movies
add column liked boolean not null default false;
```

**Migration 2: `watchlist_movies` table**
```sql
create table watchlist_movies (
    id bigint generated always as identity primary key,
    user_id uuid not null references profiles(id) on delete cascade,
    tmdb_id int not null references movies(tmdb_id),
    added_date date,
    created_at timestamptz default now(),
    unique(user_id, tmdb_id)
);
```

The `unique(user_id, tmdb_id)` constraint on both tables is what enables `ON CONFLICT DO NOTHING` — the constraint must exist for the conflict clause to target it.

## Sources

- Direct codebase inspection: `/Users/adamrose/Desktop/blnd/blnd_backend/` (HIGH confidence — actual source of truth)
- Letterboxd export ZIP inspection: `/Users/adamrose/Desktop/blnd/letterboxd-arose3000-2026-03-04-03-09-utc.zip` (HIGH confidence — real export used to confirm CSV schemas)
- Python stdlib `zipfile`, `csv`, `io` — standard library, no versioning concern (HIGH confidence)
- SQLAlchemy `insert().on_conflict_do_nothing()` — PostgreSQL dialect, well-established pattern (HIGH confidence from training + codebase already uses SQLAlchemy dialects)
- FastAPI `UploadFile.read()` — core FastAPI primitive, used throughout existing codebase (HIGH confidence)

---
*Architecture research for: Letterboxd CSV import workflow — FastAPI + SQLAlchemy + TMDB*
*Researched: 2026-03-03*
