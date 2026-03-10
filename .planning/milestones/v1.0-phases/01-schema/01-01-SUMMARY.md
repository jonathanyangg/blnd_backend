---
phase: 01-schema
plan: 01
subsystem: database
tags: [postgres, supabase, migrations, sql, schema]

# Dependency graph
requires: []
provides:
  - "liked boolean NOT NULL DEFAULT false column on watched_movies table"
  - "watchlist_movies table with id, user_id, tmdb_id, added_date, created_at, UNIQUE(user_id, tmdb_id)"
affects: [02-models, 03-import]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single-concern ALTER per migration file (one column per migration)"
    - "Supabase migration naming: {timestamp}_{descriptive_name}.sql"
    - "Lowercase SQL keywords, 4-space indent, FK references inline on column line"

key-files:
  created:
    - blnd_backend/supabase/migrations/20260304042501_add_liked_to_watched_movies.sql
    - blnd_backend/supabase/migrations/20260304042606_create_watchlist_movies.sql
  modified: []

key-decisions:
  - "liked column on watched_movies uses boolean NOT NULL DEFAULT false — backfills all existing rows to false automatically"
  - "watchlist_movies.tmdb_id FK has no ON DELETE CASCADE — movies should not vanish; only user_id cascades on profile deletion"
  - "added_date is nullable date — stores optional Letterboxd CSV date, may be absent"
  - "UNIQUE(user_id, tmdb_id) as table constraint (not inline) — matches initial_schema.sql style"
  - "Created migration files directly (timestamped) since supabase CLI not in PATH but available via npx"

patterns-established:
  - "Migration convention: single ALTER per file, lowercase keywords, 4-space indent"
  - "watchlist_movies FK pattern: user_id cascades (profile deletion), tmdb_id does not (movies persist)"

requirements-completed: [SCHM-01, SCHM-02]

# Metrics
duration: 4min
completed: 2026-03-04
---

# Phase 01 Plan 01: Schema Migrations Summary

**Two Supabase SQL migrations adding `liked boolean` to watched_movies and creating the watchlist_movies table with identity PK, cascading user FK, and UNIQUE(user_id, tmdb_id) constraint**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-04T04:23:36Z
- **Completed:** 2026-03-04T04:27:00Z
- **Tasks:** 2 of 3 fully complete (Task 3 blocked by auth gate — see below)
- **Files modified:** 2

## Accomplishments
- Created `20260304042501_add_liked_to_watched_movies.sql` — single ALTER TABLE adding `liked boolean not null default false` to watched_movies
- Created `20260304042606_create_watchlist_movies.sql` — full CREATE TABLE with 6 columns, cascading FK on user_id, non-cascading FK on tmdb_id, and UNIQUE constraint
- Both files committed to `blnd_backend` git repo (main branch)
- Migration files follow exact project convention: lowercase keywords, 4-space indent, FK on column line, UNIQUE as table constraint

## Task Commits

Each task was committed atomically (in `blnd_backend` repo):

1. **Task 1: Add liked column migration** - `f34172d` (feat)
2. **Task 2: Create watchlist_movies migration** - `15a40da` (feat)
3. **Task 3: Apply migrations to DB** - Blocked by auth gate (see below)

## Files Created/Modified
- `blnd_backend/supabase/migrations/20260304042501_add_liked_to_watched_movies.sql` - Adds liked boolean NOT NULL DEFAULT false to watched_movies
- `blnd_backend/supabase/migrations/20260304042606_create_watchlist_movies.sql` - Creates watchlist_movies table with full schema, FKs, and UNIQUE constraint

## Decisions Made
- Used `npx supabase` since the CLI binary was not in $PATH (not installed globally via brew, but available via npx v2.76.16)
- Created migration files directly with correct timestamps (the `supabase migration new` command only creates an empty timestamped file — identical outcome)
- Kept two separate migration files following the single-concern convention established by prior migrations

## Deviations from Plan

None - plan executed exactly as written (Tasks 1 and 2).

## Issues Encountered

**Task 3 — Auth Gate: `supabase db push` requires login and project link**

The Supabase CLI (via `npx supabase`) is not authenticated and the project is not linked:
- `supabase db push` failed: "Cannot find project ref. Have you run supabase link?"
- `supabase projects list` failed: "Access token not provided."

Per plan instructions: "If the Supabase CLI reports an auth error, note it — do NOT create a checkpoint:human-action for this; instead surface the error message so the user can authenticate."

**To complete Task 3, the user must:**
1. Run `npx supabase login` from `blnd_backend/` (opens browser for OAuth)
2. Run `npx supabase link --project-ref <your-project-ref>` (find ref in Supabase dashboard URL)
3. Run `npx supabase db push` — both migrations will be applied
4. Optionally verify: `npx supabase db diff --schema public` should show no drift

The migration files are complete and correct. `supabase db push` will apply them in timestamp order.

## User Setup Required

**Supabase DB push requires manual authentication.**

```bash
cd blnd_backend/
npx supabase login
npx supabase link --project-ref <your-project-ref>
npx supabase db push
```

Expected output: Both migration filenames listed as applied, exit code 0.

## Next Phase Readiness
- Migration files are complete and committed — ready for Phase 02 (SQLAlchemy models)
- DB push is pending user authentication, but model layer can be written against the committed schema
- Blocker: Task 3 (db push) requires user auth before live DB reflects the schema changes

## Self-Check: PASSED

- FOUND: `blnd_backend/supabase/migrations/20260304042501_add_liked_to_watched_movies.sql`
- FOUND: `blnd_backend/supabase/migrations/20260304042606_create_watchlist_movies.sql`
- FOUND: `.planning/phases/01-schema/01-01-SUMMARY.md`
- FOUND: commit `f34172d` (Task 1 — add liked migration)
- FOUND: commit `15a40da` (Task 2 — create watchlist_movies migration)
- FOUND: commit `70a4ae7` (docs — final metadata commit)

---
*Phase: 01-schema*
*Completed: 2026-03-04*
