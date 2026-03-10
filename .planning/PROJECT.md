# Letterboxd Import Feature

## What This Is

A backend workflow that accepts a Letterboxd data export zip file, parses the relevant CSVs (ratings, reviews, watched, watchlist, likes/films), resolves each movie to a TMDB ID via search, and persists the data to the user's account in the BLND backend. Includes production hardening with file validation, TMDB rate limiting, and per-movie error isolation.

## Core Value

Users can import their complete Letterboxd history into BLND with a single zip upload — watched movies, ratings, reviews, watchlist, and likes all transfer accurately.

## Requirements

### Validated

- Parse Letterboxd zip file and extract ratings.csv, reviews.csv, watched.csv, watchlist.csv, likes/films.csv — v1.0
- Resolve movie names + years to TMDB IDs via TMDB search API — v1.0
- Import watched movies into watched_movies table (skip existing entries) — v1.0
- Import ratings (0.5-5.0 scale) attached to watched movie entries — v1.0
- Import reviews (text + watched date) attached to watched movie entries — v1.0
- Add `liked` boolean field to watched_movies table via Supabase migration — v1.0
- Import liked films by setting liked=true on corresponding watched_movies entries — v1.0
- Create watchlist_movies table via Supabase migration — v1.0
- Import watchlist entries into watchlist_movies table — v1.0
- All logic lives in `app/import_data/workflows.py` — v1.0
- All changes made on a feature branch — v1.0

### Active

- [ ] Expose `liked` field in tracking API responses
- [ ] Watchlist read/CRUD API endpoints
- [ ] Trigger taste profile rebuild after bulk import
- [ ] Two-step TMDB search (fallback without year + year proximity scoring)
- [ ] TMDB rate limit throttling via asyncio.Semaphore
- [ ] Per-movie result detail in import response
- [ ] Async background job processing for large imports (500+ films)

### Out of Scope

- Frontend UI for the import flow — backend only
- Importing profile.csv, diary.csv, comments.csv, deleted/*, orphaned/*, likes/reviews.csv, likes/lists.csv
- Re-import / incremental import detection
- Rewatch tracking from diary.csv
- Tags import from reviews.csv

## Context

Shipped v1.0 with ~2,062 LOC Python + 179 LOC SQL.
Tech stack: FastAPI, SQLAlchemy, Supabase Postgres, httpx async TMDB client.
End-to-end verified with real Letterboxd export data.
Known tech debt: `liked` and watchlist data are write-only (no read API), taste profile not rebuilt after import.

## Constraints

- **Branch**: All changes must be on a feature branch, not main/master
- **File location**: Workflow logic goes in `app/import_data/workflows.py`
- **DB migrations**: Use Supabase migration convention (raw SQL in supabase/migrations/)
- **TMDB rate limit**: Throttled at ~40 req/s via 25ms delay per call
- **Duplicates**: Skip movies already in user's watch history (don't overwrite)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| TMDB search by name+year to resolve IDs | Letterboxd doesn't export TMDB IDs, search is the most reliable fallback | Good — works reliably for most films |
| Add `liked` boolean to watched_movies | Keeps likes tied to watched entries rather than a separate table | Good — simple schema, liked-but-not-watched creates watched entry with nulls |
| Separate watchlist_movies table | Watchlist is conceptually different from watched (user hasn't seen it yet) | Good — clean separation |
| Skip existing entries on import | Preserve existing manual entries over import data | Good — prevents data loss on re-import |
| Query-first duplicate detection | Avoid IntegrityError catch pattern for cleaner control flow | Good — explicit skip counting |
| TMDB primary_release_year parameter | Not `year` — correct TMDB API parameter for year filtering | Good — confirmed via testing |
| URI-keyed union merge for CSV consolidation | Films appear across multiple CSVs; URI is the stable Letterboxd identifier | Good — captures 100% of films |
| 25ms rate limit delay (unconditional) | Applied after every TMDB call, even cache hits — simple and safe | Good — ~40 req/s stays under TMDB limit |
| 10MB upload limit + decompression ratio 100 | Conservative defaults for production safety | Good — prevents abuse |
| db.rollback() before logging in exception handler | Resets session state before any further work to prevent cascading failures | Good — enables per-movie isolation |

---
*Last updated: 2026-03-09 after v1.0 milestone*
