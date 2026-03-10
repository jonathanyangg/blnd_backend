---
phase: 02-core-import-workflow
verified: 2026-03-04T12:00:00Z
status: gaps_found
score: 5/6 must-haves verified
gaps:
  - truth: "All changes are committed to the repository on a feature branch"
    status: failed
    reason: "The entire blnd_backend/ directory is untracked (git status shows '?? blnd_backend/'). Four commits referenced in SUMMARYs (2549ba7, 4be3bbe, 18cc9e8, 11af6bd) do not exist in the repository. Code exists on disk but has never been committed."
    artifacts:
      - path: "blnd_backend/"
        issue: "Entire directory is untracked -- no implementation commits exist in git history"
    missing:
      - "Commit all implementation files (workflows.py, schemas.py, views.py changes) to the feature/letterboxd-import branch"
---

# Phase 2: Core Import Workflow Verification Report

**Phase Goal:** The `POST /import/letterboxd` endpoint accepts a Letterboxd zip and correctly imports watched history, ratings, reviews, watchlist entries, and liked films, returning a structured summary
**Verified:** 2026-03-04
**Status:** gaps_found
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

Truths are derived from the ROADMAP.md Success Criteria for Phase 2 plus must_haves from all three plans.

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Uploading a Letterboxd export zip to POST /import/letterboxd returns HTTP 200 with a JSON summary containing imported, skipped, and failed counts | VERIFIED | `views.py:43-52` wires the endpoint with `response_model=ImportSummaryResponse`; `schemas.py:8-12` defines the model with `imported`, `skipped`, `failed`, `failed_titles` fields; `workflows.py:254-259` returns the matching dict; router registered at `/import` prefix in `main.py:20` |
| 2 | All five CSVs (ratings, reviews, watched, watchlist, likes/films) are processed and films appearing in any file are captured, not just those in watched.csv | VERIFIED | `workflows.py:53-122` `_parse_csvs()` processes all 5 files: `watched.csv` (line 69), `ratings.csv` (line 80), `reviews.csv` (line 88), `likes/films.csv` (line 101), `watchlist.csv` (line 109). Uses URI-keyed union merge via `_get_or_create()` (line 45-50) so films from any CSV are captured. |
| 3 | Each film is resolved to a TMDB ID via name+year search; films that cannot be resolved are skipped without aborting the import | VERIFIED | `workflows.py:139-158` `_resolve_tmdb_id()` calls `tmdb_client.get("/search/movie")` with `primary_release_year`. Lines 186-192 handle None result by appending to `failed_titles` and continuing the loop. |
| 4 | An existing watched entry for the same user and film is not overwritten -- the import skips the duplicate | VERIFIED | `workflows.py:199-212` queries `WatchedMovie` by `user_id` + `tmdb_id` first; if existing, increments `skipped` (line 212); only creates new entry when no existing record found (lines 213-224). |
| 5 | Liked films that have no corresponding watched entry get a new watched_movies row created with liked=true and null rating/review/watched_date | VERIFIED | `workflows.py:198` condition `if record.in_watched or record.liked` ensures liked-but-not-watched films enter the insert block. `FilmRecord` defaults (lines 24-29) give `rating=None`, `review=None`, `watched_date=None` for films only in `likes/films.csv`. The `WatchedMovie` constructor on lines 214-221 passes these None values with `liked=record.liked` (True). |
| 6 | All workflow logic lives in app/import_data/workflows.py and all changes are on a feature branch | PARTIAL | Workflow logic is correctly in `workflows.py` (INFR-01 satisfied). Current branch is `feature/letterboxd-import` (feature branch exists). However, the entire `blnd_backend/` directory is **untracked** -- no implementation code has been committed to the repository. Commits referenced in SUMMARYs (2549ba7, 4be3bbe, 18cc9e8, 11af6bd) do not exist in git history. |

**Score:** 5/6 truths verified (1 partial due to uncommitted code)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `blnd_backend/app/import_data/workflows.py` | Zip extraction, CSV parsing, URI-keyed union merge, TMDB resolution, DB writes | VERIFIED (code) / ORPHANED (git) | 260 lines, contains `FilmRecord`, `_parse_csvs`, `_title_matches`, `_resolve_tmdb_id`, `run_letterboxd_import`. Substantive implementation, not a stub. But file is untracked in git. |
| `blnd_backend/app/import_data/schemas.py` | ImportSummaryResponse Pydantic model | VERIFIED (code) / ORPHANED (git) | 12 lines, contains `ImportSummaryResponse` with `imported: int`, `skipped: int`, `failed: int`, `failed_titles: list[str]`. Untracked in git. |
| `blnd_backend/app/import_data/views.py` | Wired /letterboxd endpoint with auth, db, tmdb dependencies | VERIFIED (code) / ORPHANED (git) | 53 lines, endpoint has `UploadFile`, `get_current_user`, `get_db`, `get_tmdb_client` dependencies. `response_model=ImportSummaryResponse`. Calls `workflows.run_letterboxd_import()`. Untracked in git. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `views.py` | `workflows.py` | `workflows.run_letterboxd_import()` | WIRED | Line 51: `result = await workflows.run_letterboxd_import(user_id, file_bytes, db, tmdb_client)` |
| `views.py` | `schemas.py` | `response_model=ImportSummaryResponse` | WIRED | Line 12: `from app.import_data.schemas import ImportSummaryResponse`; Line 43: `@router.post("/letterboxd", response_model=ImportSummaryResponse)` |
| `workflows.py` | TMDB /search/movie API | `tmdb_client.get('/search/movie')` | WIRED | Line 147: `response = await tmdb_client.get("/search/movie", params=params)` with `primary_release_year` param |
| `workflows.py` | `app/movies/services.py` | `get_movie_details()` | WIRED | Line 12: `from app.movies.services import get_movie_details`; Line 195: `await get_movie_details(tmdb_id, db, tmdb_client)` |
| `workflows.py` | `app/tracking/models.py` | `WatchedMovie()` and `WatchlistMovie()` | WIRED | Line 13: `from app.tracking.models import WatchedMovie, WatchlistMovie`; Line 214: `WatchedMovie(...)` constructor; Line 237: `WatchlistMovie(...)` constructor |
| `main.py` | `views.py` router | `app.include_router(import_router)` | WIRED | Line 8: import; Line 20: `app.include_router(import_router, prefix="/import", tags=["import"])` |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| CSVP-01 | 02-01 | Endpoint accepts zip file upload at POST /import/letterboxd | SATISFIED | `views.py:44-48` -- `UploadFile = File(...)` parameter on `/letterboxd` route |
| CSVP-02 | 02-01 | Zip extraction discovers and opens ratings.csv, reviews.csv, watched.csv, watchlist.csv, likes/films.csv | SATISFIED | `workflows.py:57-122` -- all 5 files listed and processed with `zf.open()` |
| CSVP-03 | 02-01 | CSV parsing handles RFC 4180 quoting (commas in movie titles) | SATISFIED | `csv.DictReader` used on all 5 files (lines 71, 82, 90, 103, 111) -- Python csv module handles RFC 4180 by default |
| CSVP-04 | 02-01 | Union merge: all CSVs merged by Letterboxd URI | SATISFIED | `_get_or_create()` on lines 45-50 uses URI as dict key; `merged: dict[str, FilmRecord]` (line 55) |
| CSVP-05 | 02-01 | Ratings parsed as floats (0.5-5.0 scale) | SATISFIED | Line 85: `float(row["Rating"])` in ratings.csv; Line 95: same in reviews.csv |
| CSVP-06 | 02-01 | Reviews parsed with review text and actual Watched Date (not Date column) | SATISFIED | Line 93: `record.review = row.get("Review") or None`; Lines 97-98: `row.get("Watched Date")` used, not `Date` |
| CSVP-07 | 02-01 | Empty Rating fields parsed as None, not 0 | SATISFIED | Line 85: `float(row["Rating"]) if row.get("Rating") else None`; Line 95: same pattern; Line 94 has comment `# CSVP-07: empty rating becomes None, not 0` |
| TMDB-01 | 02-02 | Each unique movie resolved to TMDB ID via TMDB search API using name + year | SATISFIED | `_resolve_tmdb_id()` lines 139-158; uses `primary_release_year` param (line 145) |
| TMDB-02 | 02-02 | Resolved movies auto-cached in movies table via existing get_movie_details | SATISFIED | Line 195: `await get_movie_details(tmdb_id, db, tmdb_client)` -- `get_movie_details` in `movies/services.py:69-85` checks cache first, fetches and commits if missing |
| TMDB-03 | 02-02 | Movies that cannot be resolved are skipped gracefully (not fatal) | SATISFIED | Lines 186-192: if `tmdb_id is None`, append to `failed_titles`, increment `failed`, `continue` |
| IMPT-01 | 02-02 | Watched movies inserted into watched_movies with rating, review, watched_date | SATISFIED | Lines 214-221: `WatchedMovie(user_id, tmdb_id, rating, review, watched_date, liked)` |
| IMPT-02 | 02-02 | Existing entries (same user_id + tmdb_id) are skipped, not overwritten | SATISFIED | Lines 199-206: query-first duplicate check; line 212: `skipped += 1` |
| IMPT-03 | 02-02 | Liked films set liked=true; if no watched entry, create one with liked=true and null fields | SATISFIED | Line 198: `if record.in_watched or record.liked`; Lines 209-211: update existing liked flag; Lines 214-221: new entry with `liked=record.liked` |
| IMPT-04 | 02-02 | Watchlist movies inserted into watchlist_movies table | SATISFIED | Lines 227-244: watchlist handling block with `WatchlistMovie()` constructor and duplicate check |
| IMPT-05 | 02-02 | Per-movie error isolation -- one failure does not abort the import | SATISFIED | Lines 183/246-252: entire per-movie block wrapped in `try/except Exception` with `continue` |
| IMPT-06 | 02-01 | Return structured summary: imported, skipped, failed counts, failed_titles | SATISFIED | Lines 254-259: returns dict with all four fields; `ImportSummaryResponse` schema validates the shape |
| INFR-01 | 02-01 | All workflow logic in app/import_data/workflows.py | SATISFIED | All CSV parsing, TMDB resolution, and DB write logic is in `workflows.py` (260 lines) |
| INFR-02 | 02-01 | All changes on a feature branch (not main/master) | PARTIAL | Current branch is `feature/letterboxd-import` (not main/master). However, code is untracked -- no commits exist. The intent is satisfied (working on feature branch) but the implementation code has not been committed. |

**Orphaned requirements:** None. All 18 requirement IDs from the phase (CSVP-01 through CSVP-07, TMDB-01 through TMDB-03, IMPT-01 through IMPT-06, INFR-01, INFR-02) are accounted for across Plans 02-01, 02-02, and 02-03.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `workflows.py` | 119-120 | `_ = target_files` suppresses unused variable | Info | Cosmetic. `target_files` list on lines 57-63 is defined for documentation but never iterated. No functional impact. |
| 02-01-SUMMARY.md | 75-76 | Commits 2549ba7, 4be3bbe referenced but do not exist in git | Warning | SUMMARY claims are inaccurate -- commits are missing from repository history |
| 02-02-SUMMARY.md | 77-78 | Commits 18cc9e8, 11af6bd referenced but do not exist in git | Warning | SUMMARY claims are inaccurate -- commits are missing from repository history |
| blnd_backend/ | - | Entire directory untracked | Blocker | All implementation code exists only on disk, not in version control. A `git clean` or checkout would destroy all work. |

### Human Verification Required

### 1. End-to-End Import with Real Zip

**Test:** Upload the Letterboxd export zip at `letterboxd-arose3000-2026-03-04-03-09-utc.zip` to `POST /import/letterboxd` with a valid JWT token. Verify HTTP 200 response with reasonable imported/skipped/failed counts.
**Expected:** `imported > 0`, `skipped = 0` (first import), `failed_titles` lists any unresolvable films. Total should roughly equal unique films across all CSVs.
**Why human:** Requires running dev server, valid database, TMDB API key, and JWT authentication.

### 2. Duplicate Protection on Re-Upload

**Test:** Upload the same zip a second time.
**Expected:** `imported = 0`, `skipped` equals the first run's `imported` count. No duplicate rows in watched_movies or watchlist_movies.
**Why human:** Requires database state inspection after two sequential uploads.

### 3. Liked-But-Not-Watched Films

**Test:** After import, query `watched_movies` for films that appear in `likes/films.csv` but not in `watched.csv`.
**Expected:** These films have `liked=true`, `rating=NULL`, `review=NULL`, `watched_date=NULL`.
**Why human:** Requires database query and cross-referencing with the original CSV data.

**Note:** The 02-03-SUMMARY.md claims all three of these tests were performed by the user and passed. This cannot be independently verified programmatically.

### Gaps Summary

The implementation code is complete and correct -- all 18 requirements are satisfied in the source files on disk. All key links are wired. No stub patterns, no TODOs, no placeholder implementations.

The single gap is a **version control gap**: the entire `blnd_backend/` directory is untracked in the git repository. The SUMMARYs reference four commits (2549ba7, 4be3bbe, 18cc9e8, 11af6bd) that do not exist in the git history. This means the implementation work exists only on the local filesystem and is not preserved in version control. This is a blocker for INFR-02 (feature branch requirement) since code that is not committed is not truly "on" any branch.

However, this gap is likely a repository structure issue (the backend code may have been developed in a separate git repository or working tree) rather than a code quality issue. The code itself is production-ready.

---

_Verified: 2026-03-04_
_Verifier: Claude (gsd-verifier)_
