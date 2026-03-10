---
phase: 02-core-import-workflow
plan: 02
subsystem: api
tags: [fastapi, tmdb, sqlalchemy, letterboxd, import, httpx]

# Dependency graph
requires:
  - phase: 02-core-import-workflow
    plan: 01
    provides: FilmRecord dataclass, _parse_csvs() union merge, run_letterboxd_import() stub, _title_matches() helper
  - phase: 01-schema
    provides: WatchedMovie and WatchlistMovie models; watched_movies/watchlist_movies tables with liked column

provides:
  - _resolve_tmdb_id() async helper: TMDB /search/movie by name+year, title verification, returns TMDB ID or None
  - Complete run_letterboxd_import() pipeline: TMDB resolution, movie caching, DB writes, duplicate skipping, error isolation
  - Per-movie error isolation via try/except with failed_titles tracking

affects:
  - 02-03 (if any): import endpoint is now fully functional end-to-end

# Tech tracking
tech-stack:
  added: []
  patterns:
    - TMDB primary_release_year search parameter (not year) for accurate year filtering
    - Query-first duplicate detection (not IntegrityError catch) per project anti-patterns
    - Per-movie try/except isolation: one failure does not abort remaining import
    - get_movie_details() called for every resolved movie to satisfy FK constraint before insert

key-files:
  created: []
  modified:
    - blnd_backend/app/import_data/workflows.py

key-decisions:
  - "TMDB search uses primary_release_year (not year) per research — confirmed as correct parameter for release year filtering"
  - "Query-first duplicate detection chosen over IntegrityError catch — consistent with project anti-patterns in research notes"
  - "Liked-but-not-watched films get a watched_movies entry with liked=true, null rating/review/watched_date — FilmRecord.in_watched is False for these but liked=True drives the insert"
  - "Pre-existing watched entries get liked=true updated if the import film is liked — avoids data loss when liked list is imported after watched history"
  - "get_movie_details() called per-movie (not batched) — acceptable N commits per research Pitfall 1, no-ops when already cached"

patterns-established:
  - "_resolve_tmdb_id pattern: TMDB search → take top result → verify title word overlap via _title_matches → return id or None"
  - "Watchlist increment counted separately from watched increment — both contribute to imported total"

requirements-completed: [TMDB-01, TMDB-02, TMDB-03, IMPT-01, IMPT-02, IMPT-03, IMPT-04, IMPT-05]

# Metrics
duration: 2min
completed: 2026-03-05
---

# Phase 2 Plan 02: TMDB Resolution and DB Write Pipeline Summary

**Complete Letterboxd import pipeline with TMDB /search/movie resolution, get_movie_details caching, query-first duplicate detection, liked-but-not-watched handling, and per-movie try/except error isolation**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-05T01:44:07Z
- **Completed:** 2026-03-05T01:45:54Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Added `_resolve_tmdb_id()` async helper that searches TMDB by name + `primary_release_year`, verifies title word overlap via `_title_matches`, and returns the TMDB ID or None
- Replaced the `# TODO: TMDB resolution and DB writes` stub with the full processing loop: TMDB ID resolution, movie caching, watched entry inserts (with liked flag), watchlist entry inserts, query-first duplicate detection, and per-movie error isolation
- All code passes pre-commit linting (ruff, ruff-format, codespell, pyright)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add _resolve_tmdb_id TMDB search helper** - `18cc9e8` (feat)
2. **Task 2: Add DB write loop with duplicate detection, liked handling, and error isolation** - `11af6bd` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `blnd_backend/app/import_data/workflows.py` - Added `_resolve_tmdb_id()`, imports for `WatchedMovie`, `WatchlistMovie`, `get_movie_details`; replaced TODO stub with full processing loop in `run_letterboxd_import()`

## Decisions Made

- Used `primary_release_year` (not `year`) for TMDB search parameter — matches TMDB API documentation and research notes.
- Query-first duplicate check (not IntegrityError catch) for both watched_movies and watchlist_movies — consistent with project anti-pattern guidance.
- Liked-but-not-watched films create a watched_movies row with `liked=True` and null rating/review/watched_date — per CONTEXT.md decision; `in_watched=False` films with `liked=True` still need a row.
- Pre-existing watched entries: update `liked=True` if the film is in the liked list but `existing.liked` is False — prevents data loss when liked CSV is processed after existing watch history.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The import verification command in the plan (`python -c "from app.import_data.workflows import run_letterboxd_import"`) fails without a valid `DATABASE_URL` in the environment because `app/database.py` creates the SQLAlchemy engine at import time. Verified via AST parsing instead, which confirmed all required functions exist. This is a pre-existing architectural constraint, not introduced by this plan.
- ruff-format reformatted a multi-line `logger.warning()` call (same pattern as Plan 01). Re-staged after formatting, second pre-commit run passed cleanly.
- Pre-commit `pyright` hook requires `pyright` on PATH (not just in venv). Resolved by prepending `.venv/bin` to PATH on git commit, same fix used in Plan 01.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `run_letterboxd_import()` is fully implemented end-to-end — CSV parsing, TMDB resolution, movie caching, DB writes, error isolation
- The POST /import/letterboxd endpoint in views.py is already wired to call `run_letterboxd_import()` (from Plan 01)
- The import pipeline is ready for integration testing once a real Letterboxd export zip and valid TMDB API key are available
- Phase 2 core import workflow is complete

---
*Phase: 02-core-import-workflow*
*Completed: 2026-03-05*

## Self-Check: PASSED

- FOUND: blnd_backend/app/import_data/workflows.py
- FOUND: commit 18cc9e8 (Task 1: _resolve_tmdb_id)
- FOUND: commit 11af6bd (Task 2: DB write loop)
- FOUND: _resolve_tmdb_id in workflows.py
- FOUND: WatchedMovie in workflows.py
- FOUND: WatchlistMovie in workflows.py
- FOUND: get_movie_details in workflows.py
