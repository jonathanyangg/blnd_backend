# Letterboxd Import Feature

## What This Is

A backend workflow that accepts a Letterboxd data export zip file, parses the relevant CSVs (ratings, reviews, watched, watchlist, likes/films), resolves each movie to a TMDB ID via search, and persists the data to the user's account in the BLND backend.

## Core Value

Users can import their complete Letterboxd history into BLND with a single zip upload — watched movies, ratings, reviews, watchlist, and likes all transfer accurately.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Parse Letterboxd zip file and extract ratings.csv, reviews.csv, watched.csv, watchlist.csv, likes/films.csv
- [ ] Resolve movie names + years to TMDB IDs via TMDB search API
- [ ] Import watched movies into watched_movies table (skip existing entries)
- [ ] Import ratings (0.5-5.0 scale) attached to watched movie entries
- [ ] Import reviews (text + tags + watched date) attached to watched movie entries
- [ ] Add `liked` boolean field to watched_movies table via Supabase migration
- [ ] Import liked films by setting liked=true on corresponding watched_movies entries
- [ ] Create watchlist_movies table via Supabase migration
- [ ] Import watchlist entries into watchlist_movies table
- [ ] All logic lives in `app/import_data/workflows.py`
- [ ] All changes made on a feature branch

### Out of Scope

- Frontend UI for the import flow — backend only
- Importing profile.csv, diary.csv, comments.csv, deleted/*, orphaned/*, likes/reviews.csv, likes/lists.csv
- Background job queue / async task processing — synchronous workflow for now
- Re-import / incremental import detection

## Context

- Existing BLND backend is FastAPI + SQLAlchemy + Supabase Postgres
- WatchedMovie model exists with user_id, tmdb_id, rating, review, watched_date
- TMDB client is already configured as a dependency (httpx async)
- Movie caching via `get_movie_details` ensures FK constraint on movies table
- Letterboxd exports use Letterboxd URIs (boxd.it links), not TMDB IDs
- Rating scale matches: Letterboxd 0.5-5.0, DB check constraint 0.5-5.0
- CSV files may have commas in movie names (quoted fields)
- Import endpoint stub already exists at POST /import/letterboxd

## Constraints

- **Branch**: All changes must be on a feature branch, not main/master
- **File location**: Workflow logic goes in `app/import_data/workflows.py`
- **DB migrations**: Use Supabase migration convention (raw SQL in supabase/migrations/)
- **TMDB rate limit**: ~40 req/s — may need throttling for large imports
- **Duplicates**: Skip movies already in user's watch history (don't overwrite)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| TMDB search by name+year to resolve IDs | Letterboxd doesn't export TMDB IDs, search is the most reliable fallback | — Pending |
| Add `liked` boolean to watched_movies | Keeps likes tied to watched entries rather than a separate table | — Pending |
| Separate watchlist_movies table | Watchlist is conceptually different from watched (user hasn't seen it yet) | — Pending |
| Skip existing entries on import | User chose to preserve existing manual entries over import data | — Pending |

---
*Last updated: 2026-03-03 after initialization*
