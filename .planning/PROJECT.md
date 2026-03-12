# BLND

## Current Milestone: v1.2 Revamp Other User Profile View

**Goal:** Give users a rich profile view when tapping into a friend's profile — showing their watched movies, stats, and social connections — matching the depth of the user's own profile (minus watchlist).

**Target features:**
- Backend: public profile endpoint with stats (watched count, friends count, groups count)
- Backend: endpoint to fetch another user's watched movies (paginated)
- Backend: endpoint to fetch another user's friends list
- iOS: revamped FriendProfileView with stats row, watched poster grid, tappable friends/movies

## What This Is

A Letterboxd integration spanning backend and iOS frontend. The backend accepts a Letterboxd export zip, parses CSVs, resolves movies via TMDB, and persists the data. The iOS app provides a native UI to trigger the import, show progress and results, and surfaces the imported data (watched, ratings, reviews).

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

- [ ] Backend public profile endpoint with stats (watched count, friends count, groups count) — v1.2
- [ ] Backend endpoint to fetch another user's watched movies (paginated) — v1.2
- [ ] Backend endpoint to fetch another user's friends list — v1.2
- [ ] iOS revamped FriendProfileView with stats, watched grid, tappable navigation — v1.2

### Out of Scope

- Importing profile.csv, diary.csv, comments.csv, deleted/*, orphaned/*, likes/reviews.csv, likes/lists.csv
- Re-import / incremental import detection
- Rewatch tracking from diary.csv
- Tags import from reviews.csv

## Context

v1.0 shipped backend pipeline: ~2,062 LOC Python + 179 LOC SQL. Endpoint: `POST /import/letterboxd`.
Backend stack: FastAPI, SQLAlchemy, Supabase Postgres, httpx async TMDB client.
Frontend stack: SwiftUI iOS 17+, `@Observable`, `async/await`, `APIClient` singleton, zero third-party deps.
Design: dark monochrome, Cal.com/X aesthetic — movie posters provide all color.
Taste profile not rebuilt after import (v1.1 target). Liked/watchlist data write-only via import (deferred beyond v1.1).
v1.1 added iOS frontend features: webview import flow, results display, backend taste profile rebuild hook.
v1.2 adds public user profile endpoints and revamps the friend profile view to show watched movies, stats, and social connections.

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
*Last updated: 2026-03-11 after v1.2 milestone start*
