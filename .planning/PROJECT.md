# BLND

## What This Is

BLND is a social movie app — iOS frontend + FastAPI backend. Users track watched movies, rate them, get AI-powered recommendations, manage friends/groups, and import their Letterboxd history. Friend profiles show rich data (stats, watched movies, social connections).

## Core Value

Personalized movie recommendations powered by taste embeddings, with deep social features that let friends share and discover movies together.

## Requirements

### Validated

- ✓ Parse Letterboxd zip file and extract ratings.csv, reviews.csv, watched.csv, watchlist.csv, likes/films.csv — v1.0
- ✓ Resolve movie names + years to TMDB IDs via TMDB search API — v1.0
- ✓ Import watched movies into watched_movies table (skip existing entries) — v1.0
- ✓ Import ratings (0.5-5.0 scale) attached to watched movie entries — v1.0
- ✓ Import reviews (text + watched date) attached to watched movie entries — v1.0
- ✓ Add `liked` boolean field to watched_movies table via Supabase migration — v1.0
- ✓ Import liked films by setting liked=true on corresponding watched_movies entries — v1.0
- ✓ Create watchlist_movies table via Supabase migration — v1.0
- ✓ Import watchlist entries into watchlist_movies table — v1.0
- ✓ iOS in-app Letterboxd import flow with webview + download interception — v1.1
- ✓ Backend taste profile auto-rebuild after bulk import — v1.1
- ✓ Backend public profile endpoints (stats, watched, friends) with friendship gate — v1.2
- ✓ iOS FriendProfileView with stats, poster grid, friends list, recursive navigation — v1.2
- ✓ Shared SwiftUI components (PosterTile, StatsRow, PosterGrid) — v1.2

### Active

(No active milestone — ready for next milestone planning)

### Out of Scope

- Importing profile.csv, diary.csv, comments.csv, deleted/*, orphaned/*, likes/reviews.csv, likes/lists.csv
- Re-import / incremental import detection
- Rewatch tracking from diary.csv
- Tags import from reviews.csv

## Context

Shipped through v1.2. Codebase: ~8,250 LOC Swift (iOS), ~1,100 LOC Python (backend app code).
Backend stack: FastAPI, SQLAlchemy, Supabase Postgres, pgvector, httpx async TMDB client, OpenAI embeddings.
Frontend stack: SwiftUI iOS 17+, `@Observable`, `async/await`, `APIClient` singleton, zero third-party deps.
Design: dark monochrome, Cal.com/X aesthetic — movie posters provide all color.
v1.0: Letterboxd backend import pipeline. v1.1: iOS import flow + taste rebuild. v1.2: Public profile endpoints + FriendProfileView revamp.

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
| Public profile endpoints in auth/ domain | 3 read-only endpoints don't justify a new domain folder | ✓ Good — clean, minimal |
| Dedicated PublicProfileResponse schema | Don't reuse UserResponse — leaks taste_bio/favorite_genres | ✓ Good — privacy boundary |
| Friendship gate (403, not 404) | Explicit authorization check, not obscuring existence | ✓ Good — clear security |
| Extract shared components before FriendProfileView | PosterTile/StatsRow/PosterGrid reusable by both ProfileView and FriendProfileView | ✓ Good — clean refactor |

---
*Last updated: 2026-03-13 after v1.2 milestone*
