---
phase: 02-core-import-workflow
plan: 01
subsystem: api
tags: [fastapi, pydantic, csv, zipfile, letterboxd, import]

# Dependency graph
requires:
  - phase: 01-schema
    provides: WatchedMovie and WatchlistMovie models; DB schema with liked column and watchlist_movies table

provides:
  - ImportSummaryResponse Pydantic schema in app/import_data/schemas.py
  - workflows.py with FilmRecord dataclass, _parse_csvs() union merge, run_letterboxd_import() stub
  - POST /import/letterboxd endpoint wired with auth, DB, and TMDB client dependencies

affects:
  - 02-02 (TMDB resolution and DB writes will extend run_letterboxd_import() stub)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - URI-keyed union merge dict for multi-source CSV consolidation
    - zipfile + io.BytesIO + csv.DictReader for in-memory zip/CSV parsing
    - Graceful CSV file absence handling via zf.namelist() membership check

key-files:
  created:
    - blnd_backend/app/import_data/workflows.py
  modified:
    - blnd_backend/app/import_data/schemas.py
    - blnd_backend/app/import_data/views.py

key-decisions:
  - "Processing order: watched.csv → ratings.csv → reviews.csv → likes/films.csv → watchlist.csv (ratings/reviews overwrite minimal watched entry)"
  - "Empty Rating strings parsed as None (not 0.0) to satisfy DB check constraint 0.5–5.0"
  - "Watched Date from reviews.csv takes priority over Date from watched.csv for watched_date field"
  - "likes/films.csv opened at full subdirectory path (not films.csv) per real export structure"

patterns-established:
  - "_get_or_create pattern: look up URI in merged dict, create FilmRecord if missing, return ref"
  - "_make_record helper: centralizes safe year parsing with try/except for non-numeric values"
  - "Missing CSV files skipped gracefully via `if name in zf.namelist()` check"

requirements-completed: [CSVP-01, CSVP-02, CSVP-03, CSVP-04, CSVP-05, CSVP-06, CSVP-07, IMPT-06, INFR-01, INFR-02]

# Metrics
duration: 2min
completed: 2026-03-05
---

# Phase 2 Plan 01: CSV Parsing Foundation and Endpoint Wiring Summary

**Letterboxd zip/CSV union merge foundation using stdlib zipfile+csv.DictReader with URI-keyed FilmRecord dict, wired to POST /import/letterboxd with JWT auth + DB + TMDB client dependencies**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-05T01:39:07Z
- **Completed:** 2026-03-05T01:41:13Z
- **Tasks:** 2
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- Created `workflows.py` with `FilmRecord` dataclass and `_parse_csvs()` that extracts all 5 Letterboxd CSVs from a zip into a URI-keyed union merge dict
- Added `ImportSummaryResponse` Pydantic model (imported, skipped, failed, failed_titles) to schemas.py
- Replaced stub `/letterboxd` endpoint with fully wired version accepting UploadFile with JWT auth, DB session, and TMDB httpx client dependencies

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ImportSummaryResponse schema and wire endpoint** - `2549ba7` (feat)
2. **Task 2: Create workflows.py with zip extraction, CSV parsing, and union merge** - `4be3bbe` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `blnd_backend/app/import_data/workflows.py` - FilmRecord dataclass, _parse_csvs() union merge, _title_matches() helper, run_letterboxd_import() stub with TODO for Plan 02
- `blnd_backend/app/import_data/schemas.py` - Added ImportSummaryResponse alongside existing SeedStatusResponse
- `blnd_backend/app/import_data/views.py` - Replaced stub endpoint with UploadFile + get_current_user + get_db + get_tmdb_client wiring; response_model=ImportSummaryResponse

## Decisions Made

- Processing order for CSV merge: watched.csv first (establishes records), then ratings.csv and reviews.csv (overwrite fields), then likes/films.csv and watchlist.csv. This ensures richer data from ratings/reviews takes precedence over minimal watched.csv entries.
- Empty Rating field in reviews.csv becomes `None` (not `0.0`) — a `0.0` rating would violate the DB check constraint (0.5–5.0).
- `Watched Date` from reviews.csv overwrites `Date` from watched.csv when present, per CONTEXT.md decision.
- Opened `likes/films.csv` at the full subdirectory path to match real Letterboxd export zip structure.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pyright pre-commit hook failed on first Task 1 commit attempt because `workflows` module didn't exist yet (views.py imports it). Resolved by completing Task 2 before committing — ran both tasks then committed Task 1 and Task 2 separately. All hooks passed on final commits.
- ruff-format reformatted `workflows.py` on first Task 2 commit attempt (collapsing multi-line float expressions to single lines). Re-staged and committed successfully.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `run_letterboxd_import()` stub in `workflows.py` is the insertion point for Plan 02 (TMDB resolution and DB writes)
- `_title_matches()` helper is already in place for Plan 02's TMDB search verification
- `FilmRecord` dataclass has all fields needed for both watched_movies and watchlist_movies inserts
- All code passes pre-commit linting (ruff, ruff-format, codespell, pyright)

---
*Phase: 02-core-import-workflow*
*Completed: 2026-03-05*

## Self-Check: PASSED

- FOUND: blnd_backend/app/import_data/workflows.py
- FOUND: blnd_backend/app/import_data/schemas.py
- FOUND: blnd_backend/app/import_data/views.py
- FOUND: commit 2549ba7 (Task 1)
- FOUND: commit 4be3bbe (Task 2)
