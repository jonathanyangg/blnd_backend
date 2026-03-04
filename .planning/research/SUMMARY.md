# Project Research Summary

**Project:** BLND — Letterboxd CSV Import Pipeline
**Domain:** File upload, CSV parsing, third-party API resolution, bulk DB persistence
**Researched:** 2026-03-03
**Confidence:** HIGH

## Executive Summary

This is a well-scoped, single-endpoint feature that adds a `POST /import/letterboxd` endpoint to an existing FastAPI/SQLAlchemy/Supabase backend. The workflow accepts a Letterboxd export zip, parses five CSV files, resolves each film to a TMDB ID via name+year search, caches resolved movies, and bulk-inserts into `watched_movies` and `watchlist_movies`. Critically, zero new runtime dependencies are needed — every required capability is already in the installed stack (stdlib `zipfile`/`csv`/`io`, existing `httpx`, SQLAlchemy 2.0, FastAPI `UploadFile`). The implementation complexity lives almost entirely in two decisions: how to merge the CSV files correctly, and how to handle TMDB resolution robustly.

The recommended approach is a two-phase workflow in `app/import_data/workflows.py`: a complete TMDB resolution pass first (building a shared `(Name, Year) → tmdb_id` cache), followed by a single bulk DB write pass using PostgreSQL's `INSERT ... ON CONFLICT DO NOTHING`. This separation keeps network latency out of DB transactions, prevents partial-state corruption on TMDB failures, and enables a single commit for the entire batch. Two Supabase migrations are required before any code runs: adding a `liked` boolean to `watched_movies` and creating a new `watchlist_movies` table.

The primary risk is incorrect CSV merge logic. Direct inspection of the actual Letterboxd export confirms that 69% of liked films are absent from `watched.csv`, and reviewed films can appear in `reviews.csv` with no corresponding entry in `watched.csv` or `ratings.csv`. Any implementation that treats these files as nested subsets — rather than independent sources to union — will silently drop a significant fraction of the user's data. Every other risk (TMDB year mismatches, popularity bias, session poisoning on exception) has a well-defined, low-effort mitigation pattern documented in research.

## Key Findings

### Recommended Stack

The existing stack is complete for this feature. No new packages need to be installed. Python's stdlib `zipfile` + `csv` modules handle in-memory zip extraction and RFC 4180-compliant CSV parsing without the 30MB overhead of pandas. The existing `httpx.AsyncClient` (wired as `get_tmdb_client` in `dependencies.py`) handles TMDB search calls. SQLAlchemy 2.0's PostgreSQL dialect provides `insert().on_conflict_do_nothing()` for the skip-on-duplicate bulk insert pattern. The only conditional addition is `tenacity` for retry logic — defer until integration testing reveals a need.

**Core technologies:**
- `zipfile` + `io.BytesIO` (stdlib): In-memory zip extraction — zero dependencies, safe, no temp files on disk
- `csv.DictReader` + `io.TextIOWrapper` (stdlib): RFC 4180-compliant CSV parsing — handles quoted commas in movie titles natively
- `httpx.AsyncClient` (existing, 0.28.1): TMDB `/search/movie` resolution — already wired as a FastAPI dependency
- `sqlalchemy.dialects.postgresql.insert` (existing, 2.0.46): `ON CONFLICT DO NOTHING` bulk insert — single statement, no N+1 SELECT pattern
- `asyncio.Semaphore` (stdlib): TMDB concurrency cap for large imports — no additional install needed

**Critical version notes:**
- Must use `from sqlalchemy.dialects.postgresql import insert as pg_insert` — the generic Core `insert` does not expose `.on_conflict_do_nothing()`
- `Session.bulk_insert_mappings()` is deprecated in SQLAlchemy 2.0 — do not use

### Expected Features

Verified against the actual Letterboxd export zip at project root. All CSV schemas are confirmed ground truth.

**Must have (table stakes):**
- Zip upload and in-memory extraction — users download a zip; they expect to upload that exact file
- Parse and import `watched.csv` as the master watched list — core history data
- Parse and import `ratings.csv` — enriches watched entries with 0.5–5.0 half-star ratings
- Parse and import `reviews.csv` — enriches watched entries with review text and actual `Watched Date`
- Parse and import `watchlist.csv` into separate `watchlist_movies` table — requires migration
- Parse and import `likes/films.csv` — sets `liked=true` on watched entries; requires `liked` column migration
- TMDB name+year resolution with graceful skip on failure — Letterboxd URIs are NOT TMDB IDs
- Skip-on-duplicate for re-imports — never overwrite existing user data
- Structured import summary response — `imported`, `skipped_duplicates`, `failed` counts with failed titles

**Should have (differentiators):**
- Use `Watched Date` from `reviews.csv` as `watched_date` rather than the log creation date — more accurate watch history timeline
- TMDB rate limit throttling (asyncio.Semaphore) for imports over ~40 films — prevents 429 failures on large libraries
- Per-movie result detail in response — helps users understand exactly what failed and why

**Defer (v2+):**
- Re-import / incremental sync — conflict resolution and deletion detection are significantly complex
- `diary.csv` rewatch tracking — requires a multi-view schema model not currently present
- Tags import from `reviews.csv` — no downstream consumer in current BLND schema
- Async background job processing — synchronous is sufficient for libraries under ~500 films

**Confirmed anti-features (never build):**
- Import `profile.csv` — would overwrite BLND profile data with Letterboxd data
- Import `likes/reviews.csv` or `likes/lists.csv` — these are other users' content, not the importer's data
- Import `deleted/` or `orphaned/` directories — bookkeeping artifacts

### Architecture Approach

The entire workflow lives in `app/import_data/workflows.py` per PROJECT.md's explicit requirement. A single orchestrator function `run_letterboxd_import(zip_bytes, user_id, db, tmdb_client)` sequences six steps: extract CSVs, resolve TMDB IDs (with shared cache dict), ensure movies are cached in the `movies` table, bulk insert watched entries, bulk insert watchlist entries, and apply liked flags. `views.py` handles only HTTP concerns (file receive, auth, response shaping). The import domain reuses `movies.services.get_movie_details` for movie caching — this function already handles the cache-or-fetch pattern and satisfies the FK constraint on `movies`.

**Major components:**
1. `views.py` — HTTP endpoint: receives `UploadFile`, injects dependencies, calls workflow, returns `ImportResultResponse`
2. `workflows.py` — Orchestrator: sequences all six import steps, owns all import-specific logic
3. ZIP extractor + CSV parser — In-memory extraction via stdlib; produces five lists of row dicts keyed by Letterboxd URI
4. TMDB resolver — Two-step search (with year, then without as fallback); shared `tmdb_map` dict prevents duplicate API calls across CSVs
5. DB inserters — `pg_insert().on_conflict_do_nothing()` for watched and watchlist; `UPDATE ... WHERE tmdb_id IN (...)` for likes
6. `schemas.py` — `ImportResultResponse` Pydantic model for the summary response

**Two new migrations required (must precede code):**
- `ADD COLUMN liked boolean NOT NULL DEFAULT false` on `watched_movies`
- `CREATE TABLE watchlist_movies (id, user_id, tmdb_id, added_date, created_at, UNIQUE(user_id, tmdb_id))`

### Critical Pitfalls

1. **CSV subset assumption (CRITICAL)** — `watched.csv`, `ratings.csv`, `reviews.csv`, and `likes/films.csv` are independent sources, not nested subsets. 69% of liked films and some reviewed films have no `watched.csv` entry. Use Letterboxd URI as the merge key and union all four sources before any TMDB resolution or DB writes. This is the single highest-risk implementation mistake.

2. **TMDB popularity bias without year validation (CRITICAL)** — TMDB returns results sorted by popularity. For remakes, franchise entries, or ambiguous titles, `results[0]` is frequently the wrong film. Always validate `abs(result_year - lb_year) <= 1` before accepting a result; fall back to year-free search only when year-filtered search returns nothing.

3. **SQLAlchemy session poisoned on exception (CRITICAL)** — If any exception fires during the import loop without a `db.rollback()`, every subsequent DB operation in the same session fails with `InvalidRequestError`. Wrap each movie's processing in `try/except` with explicit `db.rollback()` in the except branch. Never let a single TMDB failure abort the entire import.

4. **TMDB year parameter is strict — off-by-one kills match (HIGH)** — Letterboxd uses festival/regional release years; TMDB uses wide release years. The difference can be one year. Implement two-step resolution: search with `year=` first, then retry without `year=` as a fallback. This is a 5-line change that prevents ~5-10% of films from silently failing.

5. **Liked films require new watched_movies rows, not just flag updates (HIGH)** — The architecture research suggests `UPDATE ... SET liked=true WHERE tmdb_id IN (...)`. This silently skips 69% of liked films that have no watched entry. When a liked film has no `watched_movies` row, create one with `liked=True` and null `rating`/`review`/`watched_date` (all columns are nullable per schema).

6. **N commits in per-movie loop (MODERATE)** — Do not reuse `track_movie()` (which calls `db.commit()` per record) for bulk imports. Use `db.flush()` per row and a single `db.commit()` after the full batch. Existing `get_movie_details` also calls `db.commit()` internally — avoid calling it inside the main import loop for movies already cached.

## Implications for Roadmap

Based on research, the dependency graph drives a clear 3-phase build order with migrations as a hard prerequisite.

### Phase 1: Migrations and Schema
**Rationale:** Both DB migrations must exist before any import code can run. The `watched_movies.liked` column and `watchlist_movies` table are referenced by FK constraints that will error at runtime if absent. These are also reversible with zero code risk — do them first.
**Delivers:** DB schema ready for all import data; no code changes needed in existing routes
**Addresses:** `liked` boolean column (FEATURES.md), `watchlist_movies` table (FEATURES.md)
**Avoids:** FK constraint errors on first import attempt; makes DB the source of truth before code is written
**Research flag:** No research needed. SQL is deterministic. Follow existing migration naming convention.

### Phase 2: Core Import Workflow
**Rationale:** This is the bulk of the implementation. All five CSV parsers, TMDB resolution with year fallback, movie caching, and the three DB write operations. Must be built as a unit because the architecture requires all TMDB resolution to complete before any DB writes begin (two-phase pattern). The CSV union merge logic must be central from the start — retrofitting it after a subset-assumption implementation means rewriting the merge layer entirely.
**Delivers:** Functional `POST /import/letterboxd` endpoint that imports watched history, ratings, reviews, watchlist, and liked films; returns structured summary
**Uses:** stdlib `zipfile`/`csv`, existing `httpx` client, `pg_insert().on_conflict_do_nothing()`, existing `get_movie_details`
**Implements:** All components in `workflows.py` per PROJECT.md requirement
**Avoids:** CSV subset assumption (Pitfall 1), session poisoning (Pitfall 3), TMDB year strictness (Pitfall 4), liked-only film rows (Pitfall 7), N commits in loop (Pitfall 6)
**Research flag:** No additional research needed. All patterns are fully specified in STACK.md and ARCHITECTURE.md. TMDB year fallback pattern and SQLAlchemy bulk insert pattern are implementation-ready.

### Phase 3: Polish and Hardening
**Rationale:** These items add correctness and UX quality but do not block the core feature. TMDB rate limiting matters only at scale (>40 films); the basic semaphore pattern is trivial to add. File size validation and zip bomb protection are security hygiene that can follow the working implementation.
**Delivers:** Rate limiting for large libraries, input validation (file size, zip safety), detailed per-movie failure reporting in response
**Addresses:** TMDB throttling (FEATURES.md P2), security mistakes (PITFALLS.md security section)
**Avoids:** TMDB 429 errors on large imports; path traversal via malicious zip; memory exhaustion from oversized uploads
**Research flag:** No additional research needed. Patterns fully specified: `asyncio.Semaphore(20)`, `Content-Length` check, sum of `file.file_size` across zip entries.

### Phase Ordering Rationale

- Migrations first because every subsequent phase depends on the schema. Running migration after code exists risks confusion about which schema version code targets.
- Core workflow as a single phase rather than "CSV parsing first, then TMDB, then DB" because the CSV union merge, TMDB resolution, and DB write are tightly coupled: the merge strategy determines what gets resolved; the resolution cache determines what gets written. Splitting them invites the subset-assumption pitfall creeping in at a seam between phases.
- Polish last because rate limiting and security hardening are additive — they do not change the core data model or workflow logic.

### Research Flags

Phases with standard patterns (no additional research needed):
- **Phase 1 (Migrations):** Raw SQL, follows existing Supabase migration convention documented in codebase
- **Phase 2 (Core Workflow):** All implementation patterns are fully specified across STACK.md and ARCHITECTURE.md; patterns are verified against actual codebase and real export zip
- **Phase 3 (Polish):** Semaphore pattern, file size validation, and zip safety patterns are fully specified in PITFALLS.md

No phases require a `gsd:research-phase` invocation. The research is comprehensive and ground-truth verified.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Verified against installed packages via PyPI, existing codebase inspection, and Python 3.11 stdlib docs. Zero dependency installs needed — this is a particularly strong finding. |
| Features | HIGH | Derived from direct inspection of the actual Letterboxd export zip in the project root, not documentation. CSV schemas are ground truth. |
| Architecture | HIGH | Based on direct codebase inspection of all relevant files. Component boundaries and build order are derived from actual code, not inference. |
| Pitfalls | HIGH | Pitfalls 1 and 7 are proven by data: 11/16 liked films and at least 1 reviewed film confirmed absent from watched.csv in the real export. Not theoretical. |

**Overall confidence:** HIGH

### Gaps to Address

- **TMDB `year` vs. `primary_release_year` parameter semantics:** WebFetch was blocked during research; TMDB year parameter behavior is inferred from the existing codebase and known TMDB API v3 patterns. Implementation should verify via a test call that `year=` in `/search/movie` does in fact filter by primary release year, not just a broad year range. Low risk — the fallback handles it either way.
- **`get_movie_details` commit behavior inside import loop:** The existing `get_movie_details` implementation calls `db.commit()` internally. If called for each movie during the movie-caching step (Step 3), this partially defeats the single-commit goal of Phase 2. Implementation should evaluate whether to batch-cache movies separately or accept N commits during the caching sub-step while using single commit for the watched_movies bulk insert.
- **Zip bomb / file size validation thresholds:** PITFALLS.md flags this as a security concern but does not specify what the correct `max_upload_size` value should be for Letterboxd exports. A typical large Letterboxd user with 5000 films produces a zip well under 5MB. Set a conservative 10MB limit in FastAPI's `max_upload_size` or via explicit validation. Validate during Phase 3.

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection: `/Users/adamrose/Desktop/blnd/blnd_backend/` — all route files, models, services, migrations, CLAUDE.md
- Letterboxd export zip: `/Users/adamrose/Desktop/blnd/letterboxd-arose3000-2026-03-04-03-09-utc.zip` — ground truth CSV schemas
- Python 3.11 stdlib docs (WebFetch verified): `csv.DictReader`, `zipfile.ZipFile`, `io.TextIOWrapper`, `io.BytesIO`
- PyPI live query: version numbers for sqlalchemy, httpx, fastapi, python-multipart, psycopg2-binary, pydantic, tenacity
- PROJECT.md: `/Users/adamrose/Desktop/blnd/.planning/PROJECT.md` — requirements and constraints

### Secondary (MEDIUM confidence)
- TMDB API v3 `/search/movie` `year` parameter behavior — inferred from existing codebase usage and known TMDB API patterns; WebFetch blocked during research
- SQLAlchemy `on_conflict_do_nothing()` behavior — confirmed against installed 2.0.46 and SQLAlchemy changelog for `bulk_insert_mappings` deprecation

### Tertiary (LOW confidence)
- Community Letterboxd importer patterns — used for competitor feature analysis only; all functional decisions are based on primary sources above

---
*Research completed: 2026-03-03*
*Ready for roadmap: yes*
