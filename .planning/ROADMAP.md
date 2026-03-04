# Roadmap: Letterboxd Import Feature

## Overview

Three phases deliver the complete Letterboxd import pipeline. Migrations ship first because every subsequent line of code depends on the schema. The core workflow ships as a single phase rather than split layers — the CSV union merge, TMDB resolution, and DB write steps are tightly coupled and splitting them invites the subset-assumption pitfall that silently drops 69% of liked films. Polish and hardening ship last because rate limiting and input validation are additive and do not change the core data model.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Schema** - Add `liked` column and create `watchlist_movies` table via Supabase migrations
- [ ] **Phase 2: Core Import Workflow** - CSV parsing, TMDB resolution, and all DB writes in `workflows.py`
- [ ] **Phase 3: Polish and Hardening** - Rate limiting, input validation, and per-movie error isolation

## Phase Details

### Phase 1: Schema
**Goal**: DB schema is ready for all import data before any import code runs
**Depends on**: Nothing (first phase)
**Requirements**: SCHM-01, SCHM-02, SCHM-03, SCHM-04
**Success Criteria** (what must be TRUE):
  1. A Supabase migration file exists that adds `liked boolean NOT NULL DEFAULT false` to `watched_movies` and applies cleanly to the database
  2. A Supabase migration file exists that creates `watchlist_movies` with the correct columns and `UNIQUE(user_id, tmdb_id)` constraint
  3. The SQLAlchemy `WatchedMovie` model has a `liked` field that reflects the new column
  4. The SQLAlchemy `WatchlistMovie` model exists and matches the new table schema
**Plans**: 2 plans

Plans:
- [ ] 01-01-PLAN.md — Create Supabase migrations (liked column + watchlist_movies table)
- [ ] 01-02-PLAN.md — Update SQLAlchemy models (WatchedMovie.liked + WatchlistMovie)

### Phase 2: Core Import Workflow
**Goal**: The `POST /import/letterboxd` endpoint accepts a Letterboxd zip and correctly imports watched history, ratings, reviews, watchlist entries, and liked films, returning a structured summary
**Depends on**: Phase 1
**Requirements**: CSVP-01, CSVP-02, CSVP-03, CSVP-04, CSVP-05, CSVP-06, CSVP-07, TMDB-01, TMDB-02, TMDB-03, IMPT-01, IMPT-02, IMPT-03, IMPT-04, IMPT-05, IMPT-06, INFR-01, INFR-02
**Success Criteria** (what must be TRUE):
  1. Uploading a Letterboxd export zip to `POST /import/letterboxd` returns HTTP 200 with a JSON summary containing `imported`, `skipped`, and `failed` counts
  2. All five CSVs (ratings, reviews, watched, watchlist, likes/films) are processed and films appearing in any file are captured, not just those in watched.csv
  3. Each film is resolved to a TMDB ID via name+year search; films that cannot be resolved are skipped without aborting the import
  4. An existing watched entry for the same user and film is not overwritten — the import skips the duplicate
  5. Liked films that have no corresponding watched entry get a new watched_movies row created with `liked=true` and null rating/review/watched_date
  6. All workflow logic lives in `app/import_data/workflows.py` and all changes are on a feature branch
**Plans**: TBD

### Phase 3: Polish and Hardening
**Goal**: The import endpoint is safe and reliable for large libraries and adversarial input
**Depends on**: Phase 2
**Requirements**: (none — this phase hardens the implementation against known risks documented in research)
**Success Criteria** (what must be TRUE):
  1. Importing a library with more than 40 films does not produce HTTP 429 errors from TMDB
  2. Uploading an oversized file or a malicious zip is rejected with a clear error response before any processing begins
  3. A single failed TMDB lookup or DB error for one film does not abort the rest of the import — the remaining films continue processing

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Schema | 0/TBD | Not started | - |
| 2. Core Import Workflow | 0/TBD | Not started | - |
| 3. Polish and Hardening | 0/TBD | Not started | - |
