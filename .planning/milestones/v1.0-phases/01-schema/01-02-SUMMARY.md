---
phase: 01-schema
plan: 02
subsystem: database
tags: [sqlalchemy, python, models, orm, tracked_movies, watchlist]

# Dependency graph
requires:
  - phase: 01-01
    provides: "liked boolean NOT NULL DEFAULT false column on watched_movies, watchlist_movies table"
provides:
  - "WatchedMovie SQLAlchemy model with liked: Mapped[bool] field (server_default='false')"
  - "WatchlistMovie SQLAlchemy model matching watchlist_movies table (5 columns, UniqueConstraint)"
affects: [03-import, 04-services, recommendations]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Models derived from migrations (migrations are source of truth, not the reverse)"
    - "server_default uses SQL string value ('false') not Python literal for DB-side defaults"
    - "WatchlistMovie follows WatchedMovie pattern exactly: same imports, same UUID, same datetime lambda"

key-files:
  created: []
  modified:
    - blnd_backend/app/tracking/models.py

key-decisions:
  - "liked: Mapped[bool] (not Mapped[bool | None]) because column is NOT NULL — no Python-side default needed"
  - "server_default='false' (string) instead of Python False — matches DB default without requiring application-side value for existing rows"
  - "No relationship() calls added — codebase uses raw FK columns without ORM relationships per existing convention"
  - "added_date: Mapped[date | None] with nullable=True — matches nullable date in watchlist_movies migration"

patterns-established:
  - "WatchlistMovie follows WatchedMovie layout: BigInteger PK, UUID(as_uuid=True) user_id, Integer tmdb_id, nullable date, created_at lambda"
  - "Boolean type imported from sqlalchemy (same import block, alphabetical order)"

requirements-completed: [SCHM-03, SCHM-04]

# Metrics
duration: 4min
completed: 2026-03-04
---

# Phase 01 Plan 02: SQLAlchemy Models Summary

**SQLAlchemy WatchedMovie updated with `liked: Mapped[bool]` (server_default='false') and new WatchlistMovie class added to tracking/models.py — both models exactly mirror the DB schema from plan 01-01 migrations**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-04T04:31:00Z
- **Completed:** 2026-03-04T04:35:41Z
- **Tasks:** 1 of 1 complete
- **Files modified:** 1

## Accomplishments
- Added `Boolean` import to SQLAlchemy imports block in `tracking/models.py`
- Added `liked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")` to `WatchedMovie` after `watched_date`
- Created `WatchlistMovie` class with `__tablename__ = "watchlist_movies"`, `UniqueConstraint("user_id", "tmdb_id")`, and 5 columns matching the migration exactly
- Ruff lint and format pass on the file (verified with ruff 0.14.10)

## Task Commits

Each task was committed atomically (in `blnd_backend` repo):

1. **Task 1: Add liked field to WatchedMovie and create WatchlistMovie model** - `cb7a558` (feat)

## Files Created/Modified
- `blnd_backend/app/tracking/models.py` - Added Boolean import, liked field to WatchedMovie, and full WatchlistMovie class

## Decisions Made
- Used `server_default="false"` (SQL string) not Python `False` — matches DB-level default, avoids requiring a Python-side value for existing rows that already have the column set by the migration
- Typed `liked` as `Mapped[bool]` (not `Mapped[bool | None]`) since the column is `NOT NULL` — consistent with how `id` and `tmdb_id` are typed in the same class
- No `relationship()` calls added on `WatchlistMovie` — existing models (WatchedMovie, Friendship) all use raw FK columns without ORM relationship objects

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

**Python environment not set up:** The project has no `.venv` directory — `pip install -r requirements.txt` has not been run on this machine. This means:
- `python -c "from app.tracking.models import ..."` fails with `ModuleNotFoundError: No module named 'sqlalchemy'`
- `pre-commit run --all-files` not available (pre-commit not in PATH)
- `npx pyright` reports `reportMissingImports` for all sqlalchemy imports — same errors appear on ALL existing model files, confirming this is an environment issue not a code defect

Both ruff check and ruff format pass on the file, confirming code is syntactically and stylistically correct. The code pattern exactly mirrors the existing `WatchedMovie` class which was previously working. The import errors are an environment-setup issue predating this plan.

## User Setup Required

None specific to this plan. The general environment setup (`.venv` creation) would be needed to run the full pre-commit suite, but this was already the case before this plan.

## Next Phase Readiness
- `tracking/models.py` now exports both `WatchedMovie` (with `liked`) and `WatchlistMovie`
- Both models reflect their corresponding DB tables exactly per the 01-01 migrations
- Ready for Phase 03 (import_data domain) — Letterboxd CSV parser can import to `WatchlistMovie` and set `liked` on `WatchedMovie`
- DB push from 01-01 still pending user authentication (blocker carried forward from 01-01)

## Self-Check: PASSED

- FOUND: `blnd_backend/app/tracking/models.py` (modified with liked + WatchlistMovie)
- FOUND: `liked` on line 30: `liked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")`
- FOUND: `WatchlistMovie` class with `__tablename__ = "watchlist_movies"` on lines 36-46
- FOUND: commit `cb7a558` (Task 1 — add liked + WatchlistMovie)

---
*Phase: 01-schema*
*Completed: 2026-03-04*
