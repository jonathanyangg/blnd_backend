# Requirements: Letterboxd Import

**Defined:** 2026-03-03
**Core Value:** Users can import their complete Letterboxd history into BLND with a single zip upload

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Schema

- [ ] **SCHM-01**: Supabase migration adds `liked` boolean column (default false) to `watched_movies` table
- [ ] **SCHM-02**: Supabase migration creates `watchlist_movies` table with user_id, tmdb_id, added_date, created_at, unique(user_id, tmdb_id)
- [ ] **SCHM-03**: SQLAlchemy WatchedMovie model updated with `liked` field
- [ ] **SCHM-04**: SQLAlchemy WatchlistMovie model created matching new table

### CSV Parsing

- [ ] **CSVP-01**: Endpoint accepts zip file upload at POST /import/letterboxd
- [ ] **CSVP-02**: Zip extraction discovers and opens ratings.csv, reviews.csv, watched.csv, watchlist.csv, likes/films.csv
- [ ] **CSVP-03**: CSV parsing handles RFC 4180 quoting (commas in movie titles)
- [ ] **CSVP-04**: Union merge: all CSVs merged by Letterboxd URI so films appearing in any file are captured (not just watched.csv)
- [ ] **CSVP-05**: Ratings parsed as floats (0.5-5.0 scale, including half-steps like 2.5, 3.5)
- [ ] **CSVP-06**: Reviews parsed with review text and actual `Watched Date` (not `Date` column)
- [ ] **CSVP-07**: Empty Rating fields in reviews.csv parsed as None, not 0

### TMDB Resolution

- [ ] **TMDB-01**: Each unique movie resolved to a TMDB ID via TMDB search API using name + year
- [ ] **TMDB-02**: Resolved movies auto-cached in movies table via existing `get_movie_details`
- [ ] **TMDB-03**: Movies that cannot be resolved are skipped gracefully (not fatal)

### Import Logic

- [ ] **IMPT-01**: Watched movies inserted into watched_movies with rating, review, watched_date where available
- [ ] **IMPT-02**: Existing entries (same user_id + tmdb_id) are skipped, not overwritten
- [ ] **IMPT-03**: Liked films set liked=true on corresponding watched_movies entry; if no watched entry exists, create one with liked=true and null other fields
- [ ] **IMPT-04**: Watchlist movies inserted into watchlist_movies table
- [ ] **IMPT-05**: Per-movie error isolation — one TMDB failure or DB error does not abort the entire import
- [ ] **IMPT-06**: Return structured summary: imported count, skipped count, failed count, list of failed movie titles

### Infrastructure

- [ ] **INFR-01**: All workflow logic in `app/import_data/workflows.py`
- [ ] **INFR-02**: All changes on a feature branch (not main/master)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Resolution

- **TMDB-04**: Two-step TMDB search — first with year, fallback without year + year proximity scoring
- **TMDB-05**: TMDB rate limit throttling via asyncio.Semaphore for large imports

### Enhanced Import

- **IMPT-07**: Per-movie result detail in response (resolved/skipped/failed with title + reason)
- **IMPT-08**: Rewatch tracking from diary.csv
- **IMPT-09**: Tags import from reviews.csv

### Infrastructure

- **INFR-03**: Async background job processing for large imports (500+ films)
- **INFR-04**: Re-import / incremental update detection

## Out of Scope

| Feature | Reason |
|---------|--------|
| Frontend import UI | Backend-only scope per project definition |
| Import profile.csv | BLND users already have accounts; overwriting with Letterboxd data is destructive |
| Import diary.csv | Overlaps with watched/reviews; no multi-view model in schema |
| Import deleted/orphaned directories | Deleted entries were deleted for a reason; orphaned have no valid film association |
| Import likes/reviews.csv, likes/lists.csv | Other users' content the user liked, not their own data |
| Tags as first-class data | No tagging system in BLND yet |
| Rewatch flag | No multi-view tracking model |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCHM-01 | TBD | Pending |
| SCHM-02 | TBD | Pending |
| SCHM-03 | TBD | Pending |
| SCHM-04 | TBD | Pending |
| CSVP-01 | TBD | Pending |
| CSVP-02 | TBD | Pending |
| CSVP-03 | TBD | Pending |
| CSVP-04 | TBD | Pending |
| CSVP-05 | TBD | Pending |
| CSVP-06 | TBD | Pending |
| CSVP-07 | TBD | Pending |
| TMDB-01 | TBD | Pending |
| TMDB-02 | TBD | Pending |
| TMDB-03 | TBD | Pending |
| IMPT-01 | TBD | Pending |
| IMPT-02 | TBD | Pending |
| IMPT-03 | TBD | Pending |
| IMPT-04 | TBD | Pending |
| IMPT-05 | TBD | Pending |
| IMPT-06 | TBD | Pending |
| INFR-01 | TBD | Pending |
| INFR-02 | TBD | Pending |

**Coverage:**
- v1 requirements: 22 total
- Mapped to phases: 0
- Unmapped: 22

---
*Requirements defined: 2026-03-03*
*Last updated: 2026-03-03 after initial definition*
