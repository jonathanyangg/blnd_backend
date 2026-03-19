# BLND Backend

## Tech Stack
- **Framework**: FastAPI
- **ORM**: SQLAlchemy (models + queries)
- **Migrations**: Supabase CLI (`supabase migration new`, `supabase db push`)
- **Database**: Supabase Postgres + pgvector
- **Auth**: Supabase Auth via supabase-py (JWT + admin delete) — two clients: `supabase` (public) and `supabase_admin` (service role)
- **APIs**: TMDB (movie data), OpenAI (embeddings)
- **Linting**: pre-commit hooks with ruff, codespell, pyright

## Project Structure (Domain-Driven Design)
Each domain folder (`app/auth/`, `app/movies/`, etc.) contains:
- `models.py` — SQLAlchemy models
- `schemas.py` — Pydantic request/response models
- `services.py` — Business logic + SQLAlchemy queries
- `views.py` — FastAPI router endpoints
- `workflows.py` + `flows.py` — Multi-step orchestration (only in import_data, recommendations, groups)

## Commands
- **Dev server**: `uvicorn main:app --reload`
- **New migration**: `supabase migration new <name>`
- **Push migrations**: `supabase db push`
- **Install deps**: `pip install -r requirements.txt`
- **Lint**: `pre-commit run --all-files`

## Conventions
- Env vars loaded from `.env` via pydantic-settings (defaults to `""` for pyright compatibility)
- DB queries go through SQLAlchemy ORM (connected to Supabase Postgres via `DATABASE_URL`)
- supabase-py is used ONLY for Auth (signup, login, verify JWT, admin delete user)
- Async HTTP calls use httpx
- Movie embeddings: OpenAI text-embedding-3-small (1536 dims) stored in pgvector
- Supabase SDK returns optional types — always null-check `.user` and `.session` before access
- Use `datetime.now(timezone.utc)` not `datetime.utcnow()` (deprecated)
- Migrations are raw SQL in `supabase/migrations/` — commit them to git
- Keep SQLAlchemy models in sync with migrations manually (migrations are source of truth for DB)

## Current Status

### Done
- Project scaffolding: folder structure, config, database, dependencies, main.py
- Pre-commit hooks: ruff, ruff-format, codespell, pyright (pyrightconfig.json points to .venv)
- Supabase project set up, CLI initialized and linked
- Initial migration pushed: profiles, movies, watched_movies, friendships, groups, group_members, movie_embeddings, pgvector, match_movies RPC
- Second migration pushed: added taste_bio, favorite_genres, taste_embedding to profiles
- Third migration pushed: added trailer_url to movies
- Fourth migration pushed: added director, cast (JSONB), tagline, backdrop_path, imdb_id to movies
- Fifth migration pushed: remote schema sync
- Sixth migration pushed: added liked column to watched_movies
- Seventh migration pushed: created watchlist_movies table
- Eighth migration pushed: standalone watchlists table, watchlist_id on profiles/groups, recreated watchlist_movies with watchlist_id FK
- Auth domain: models (Profile with taste fields), schemas (signup/login/profile + UpdateProfileRequest), services (Supabase Auth + SQLAlchemy), views
  - Username validation: 3–30 chars, alphanumeric + periods + underscores, no leading/trailing/consecutive special chars, auto-lowercased, uniqueness check
  - Username updatable via PATCH /auth/profile (same validation + uniqueness)
  - GET /auth/users/search?q= — prefix search (ILIKE) for friend autocomplete, excludes current user, returns up to 10 results
  - Avatar upload: Supabase Storage `avatars` bucket (public), RLS policies (SELECT: public, INSERT/UPDATE/DELETE: owner only via folder path), frontend uploads to `avatars/{user_id}/avatar.png`, sends public URL via PATCH /auth/profile `avatar_url` field
  - Password validation: min 8 chars, at least 1 uppercase letter
  - Public profile endpoints (friendship-gated via `assert_are_friends`):
    - GET /auth/users/{id}/profile — stats (watched_count, friends_count, blends_count)
    - GET /auth/users/{id}/watched — paginated watched movies (tmdb_id, title, poster, rating)
    - GET /auth/users/{id}/friends — friends list
  - Account deletion: DELETE /auth/account — permanently deletes user and all associated data (transfers group ownership to earliest member or deletes empty groups, nulls watchlist_movies.added_by, cascade deletes profile/watched/friendships/hidden, deletes personal watchlist, best-effort Supabase Auth + avatar cleanup via `supabase_admin`)
- Movies domain: fully implemented
  - Model: Movie (SQLAlchemy, includes director, cast, tagline, backdrop_path, imdb_id)
  - Schemas: MovieResponse (all fields including credits, vote_average scaled from TMDB 0-10 to 0-5 via Pydantic validator), MovieSearchResult
  - Services: TMDB search, movie detail fetch with DB caching (uses append_to_response=credits,videos for single API call), `compute_match_scores()` batch-computes personalized scores for any list of tmdb_ids
  - Views: GET /movies/trending (TMDB weekly trending, includes match_score per movie), GET /movies/top-rated (TMDB top rated, includes match_score), GET /movies/search (TMDB search, no score — computed on detail view instead), GET /movies/{tmdb_id} (cached detail + trailer + credits + match_score)
  - `match_score` = same ranking formula as recommendations (0.50*cosine + 0.20*genre + 0.20*consensus + 0.05*director + 0.05*cast), null if user has no taste profile
  - All endpoints require JWT auth
- TMDB client lifecycle: FastAPI lifespan context manager in main.py (httpx.AsyncClient with connection pooling: max_connections=100, max_keepalive=20, timeout=30s). Stored on `app.state.tmdb_client`, accessed via `get_tmdb_client` dependency.
- All domain routers registered in main.py with stub endpoints
- DB connection pooling: `pool_recycle=1800`, `pool_pre_ping=True` on SQLAlchemy engine
- JSON structured logging via python-json-logger (stdout, with timestamp/level/name/message fields)
- FastAPI server runs clean on `uvicorn main:app --reload`
- Tracking domain: fully implemented
  - Model: WatchedMovie (SQLAlchemy, matches watched_movies table with unique(user_id, tmdb_id))
  - Schemas: TrackMovieRequest, UpdateTrackingRequest, WatchedMovieResponse, WatchHistoryResponse
  - Services: track_movie (upsert, auto-caches movie via TMDB), get_watch_history (paginated, joined with movies), get_watched_movie, update_watched_movie, delete_watched_movie
  - Views: POST /tracking/ (track/upsert), GET /tracking/ (paginated history), GET /tracking/{tmdb_id}, PATCH /tracking/{tmdb_id}, DELETE /tracking/{tmdb_id}
  - All endpoints require JWT auth; POST auto-caches movie from TMDB if not in DB
  - Tracking a movie auto-removes it from the user's personal watchlist (if present)
- Friends domain: fully implemented
  - Model: Friendship (SQLAlchemy, matches friendships table with unique(requester_id, addressee_id))
  - Schemas: SendFriendRequestRequest, FriendResponse (includes friendship_id for delete), FriendRequestResponse, FriendListResponse, PendingRequestsResponse
  - Services: send_friend_request (by username, prevents self-friending, allows re-request after rejection), accept/reject (addressee only), get_friends (accepted, either party), get_pending_requests (split incoming/outgoing), remove_friend (either party)
  - Views: POST /friends/request, POST /friends/{id}/accept, POST /friends/{id}/reject, GET /friends/, GET /friends/requests, DELETE /friends/{id}
  - All endpoints require JWT auth; no migrations needed (friendships table already exists)
- Movie seed pipeline (import_data domain): fully implemented
  - Model: MovieEmbedding (SQLAlchemy, maps to existing movie_embeddings table)
  - Schemas: SeedStatusResponse
  - Services: download_tmdb_export (daily JSONL, all non-adult movies), fetch_and_cache_movies (concurrent via asyncio.Semaphore(20) + gather, 500-movie chunks, retry on 429, batch commits, skips existing, includes credits+videos), embed_movies (OpenAI text-embedding-3-small, batch 2000), run_seed_pipeline (orchestrator)
  - Views: POST /import/seed-movies (BackgroundTask, returns 202)
  - Pipeline is idempotent — safe to re-run, skips already cached/embedded movies
- Letterboxd import (import_data domain): fully implemented
  - Schemas: FilmRecord (parsed film from CSV), ImportSummaryResponse
  - Workflows: run_letterboxd_import — parses zip of 5 CSVs (watched, ratings, reviews, likes, watchlist), deduplicates by Letterboxd URI, resolves TMDB IDs via fuzzy title match, caches movies, writes WatchedMovie + WatchlistMovie entries, single batch commit
  - Views: POST /import/letterboxd (file upload, returns import summary)
  - Per-movie error isolation — one failure doesn't abort the import
- Watchlist system: fully implemented
  - Migration: standalone `watchlists` table, `watchlist_id` FK on profiles and groups, `watchlist_movies` with `watchlist_id` FK (replaces old `user_id` FK)
  - Models: Watchlist, WatchlistMovie (watchlist_id + tmdb_id + added_by)
  - Schemas: AddToWatchlistRequest, WatchlistMovieResponse, WatchlistResponse
  - Services: get_watchlist (paginated), add_to_watchlist (auto-cache from TMDB), remove_from_watchlist
  - Views: GET/POST/DELETE /watchlist/ (personal, own router), GET/POST/DELETE /groups/{id}/watchlist (group)
  - Personal watchlist moved from /tracking/watchlist to /watchlist/ (separate domain + router to avoid FastAPI route conflict with /tracking/{tmdb_id})
  - Signup auto-creates a personal watchlist for each new user
  - Letterboxd import updated to use watchlist_id instead of user_id
- Groups domain: fully implemented
  - Models: Group (id, name, created_by, watchlist_id), GroupMember (composite PK: group_id + user_id)
  - Schemas: CreateGroupRequest, UpdateGroupRequest, AddMemberRequest, GroupMemberResponse, GroupResponse, GroupDetailResponse, GroupListResponse, GroupRecMovieResponse, GroupRecommendationsResponse
  - Services: create_group (with linked watchlist), list_groups, get_group, update_group (creator only), add_member (by username, 10-member cap), kick_member (can't kick owner), leave_group (transfers ownership), delete_group (creator only, cascade)
  - Views: POST /groups/, GET /groups/, GET /groups/{id}, PATCH /groups/{id} (update name, creator only), DELETE /groups/{id}, POST /groups/{id}/members, POST /groups/{id}/members/{uid}/kick, POST /groups/{id}/leave, GET /groups/{id}/recommendations, GET/POST/DELETE /groups/{id}/watchlist
  - Group recommendations: uses shared 4-step pipeline — averages members' positive + negative embeddings, excludes union of all members' watched + hidden movies, combined genre watch counts for exploration
- Tracking domain: added `liked` field to WatchedMovieResponse schema and _to_response
- Recommendations: fixed bug where average strategy never persisted taste_embedding to profile, replaced pure Python vector math with numpy
- Recommendations domain: fully implemented
  - Schemas: RecommendedMovieResponse, RecommendationsResponse, HiddenMovieResponse, HiddenMoviesListResponse
  - Services: dual embedding strategy (switchable via `EMBEDDING_STRATEGY` in services.py):
    - `"average"` (current default): `compute_taste_embeddings()` uses 20th percentile split — positive embedding from movies at/above threshold (rating-weighted), negative from movies below threshold (weighted by MAX_RATING - rating) merged with hidden movie embeddings. Requires 10+ rated movies for rating-derived negatives.
    - `"llm"`: gpt-4o-mini generates ideal movie synopsis → embedded with text-embedding-3-small
  - Shared 4-step pipeline (`app/recommendations/pipeline.py`): used by both user and group recs
    - Step 1: pgvector candidate generation (500 items) + quality filter (vote_average >= 1.0) + re-ranking with negative penalty
    - Step 2: Softmax probabilistic sampling (500→200) + tier shuffle
    - Step 3: Exploration scoring (genre novelty + consensus + trending) on high-rated DB movies
    - Step 4: Exploration sampling + blending (85% algo / 15% exploration per page)
  - Re-ranking formula: `0.50*cosine + 0.20*genre + 0.20*consensus + 0.05*director + 0.05*cast - 0.15*negative_cosine`, clamped ≥ 0
  - Views: GET /recommendations/me, POST /recommendations/me/refresh, POST /recommendations/{tmdb_id}/hide, DELETE /recommendations/{tmdb_id}/hide, GET /recommendations/hidden
  - Hidden movies: HiddenMovie model, excluded from recs. Hidden movies contribute to negative embedding (merged with low-rated movie negatives).
  - Recommendation page limit: max 100 movies per request (was 50)
  - Taste profile auto-rebuilds in background when: user has <50 rated movies and rates/updates/deletes a movie, or updates favorite_genres via PATCH /auth/profile. Users with 50+ ratings use manual refresh only.
  - Exploration picks: movies from underrepresented genres with high vote_average, scored by `0.50*novelty + 0.40*consensus + 0.10*trending`, rescaled to P25-P75 of main scores
- Ninth migration: added `source` column to watched_movies and watchlist_movies (tracks origin: 'manual', 'recommendation', 'letterboxd_import')
- Tenth migration: added `sync_state` table (key-value store for sync pipeline state, e.g. `last_movie_sync_date`)
- Recommendation source tracking: TrackMovieRequest and AddToWatchlistRequest accept `source` field, Letterboxd import sets `source="letterboxd_import"`
- Auth domain updates:
  - Added update_profile service (updates display_name/favorite_genres, detects genre changes)
  - Added PATCH /auth/profile endpoint (triggers background taste rebuild on genre change)
  - Fixed GET /auth/me to include taste_bio and favorite_genres in response
- MovieResponse vote_average scaled from TMDB 0–10 to 0–5 via Pydantic field_validator (DB stores raw value)
- Watchlist endpoints extracted to own domain (`app/watchlist/`) at `/watchlist/` prefix (was `/tracking/watchlist`, conflicted with `/tracking/{tmdb_id}`)
- Seed pipeline: TMDB fetching parallelized (Semaphore(20) + gather, 500-movie chunks, retry on 429), now fetches `credits,videos` (trailer extraction), embed batch size 2000
- Seed pipeline uses `asyncio.ensure_future()` instead of `BackgroundTasks` (avoids `asyncio.run()` inside existing event loop)
- OpenAPI spec auto-export: `openapi.json` written to project root on first `/health` hit (for frontend context)
- Match scores on trending + top-rated + detail: `MovieResponse.match_score` computed via `compute_match_scores()` in `movies/services.py` — reuses ranking weights from `recommendations/ranking.py`
- Match score scaling: `to_match_percentage()` in `ranking.py` adds flat MATCH_BOOST (0.33) to raw score, capped at 1.0 via `min(score + MATCH_BOOST, 1.0)`. Applied to all score outputs (trending, top-rated, detail, recommendations, group recommendations). Frontend multiplies by 100 for display.
- Rate limiting: slowapi with per-user keying (JWT sub claim, fallback to IP). Tiered limits: LIMIT_HEAVY (1/day) for seed/sync, LIMIT_IMPORT (3/hour) for letterboxd, LIMIT_REFRESH (5/hour) for rec refresh, LIMIT_SEARCH (30/min) for search/discover, LIMIT_DEFAULT (60/min) for everything else. Disabled in tests via TESTING=true. Config in `app/core/rate_limit.py`.
- TMDB Changes API sync: `POST /import/sync-movies` polls TMDB Changes API for movies modified since last sync, updates cached movies in-place, re-embeds movies whose overviews changed. Uses `sync_state` table (key-value) to track `last_movie_sync_date`. `_cache_movie()` now supports upsert via `existing_movie` param and returns `(movie, overview_changed)` tuple. Migration: `sync_state` table. Rate-limited to 1/day (LIMIT_HEAVY).
- Eleventh migration: added `negative_embedding` vector(1536) to profiles, created `hidden_movies` table (user_id, tmdb_id, unique constraint)
- Auth refresh: POST /auth/refresh (accepts refresh_token, returns new access_token + refresh_token, no JWT required)
- Taste embedding overhaul: `compute_taste_embeddings()` uses 20th percentile split — positive from at/above threshold (rating-weighted), negative from below threshold (weighted by MAX_RATING - rating) merged with hidden movies. Requires 10+ rated movies for rating-derived negatives. Quality filter (vote_average >= 1.0) on pgvector candidates removes junk results.
- Hidden movies: HiddenMovie model in `app/recommendations/models.py`, CRUD in services.py, endpoints in views.py (POST/DELETE /recommendations/{tmdb_id}/hide, GET /recommendations/hidden)
- Shared recommendation pipeline: `app/recommendations/pipeline.py` — `RecommendationContext` dataclass + `run_recommendation_pipeline()` used by both user and group recs. Eliminates code duplication.
- Exploration slots: 15% of each page filled with movies from underrepresented genres (high vote_average, scored by novelty + consensus + trending). Scores rescaled to P25-P75 of main algorithm scores so they blend naturally.
- Auto-rebuild logic changed: `should_auto_rebuild()` replaces `would_affect_top_n()` — always rebuilds for <50 rated movies, never auto-rebuilds for 50+ (manual refresh via POST /recommendations/me/refresh)
- Public profile endpoints (friendship-gated): GET /auth/users/{id}/profile (stats), /watched (paginated), /friends (list). Schemas: PublicProfileResponse, PublicWatchedListResponse, PublicFriendsListResponse
- Account deletion (DELETE /auth/account): full cascade cleanup — group ownership transfer, watchlist cleanup, profile cascade, Supabase Auth + avatar deletion (best-effort)
- `supabase_admin` client in dependencies.py (service role key, for admin operations like deleting auth users)
- `get_optional_user` dependency: extracts user ID from Bearer token if present, returns None otherwise (for optional auth endpoints)
- DB connection pooling: `pool_recycle=1800`, `pool_pre_ping=True`
- TMDB client moved to FastAPI lifespan (httpx.AsyncClient with connection limits, stored on app.state)
- JSON structured logging via python-json-logger
- MATCH_BOOST bumped from 0.12 → 0.33
- Recommendation page limit bumped from 50 → 100
- Password validation on signup (min 8 chars, 1 uppercase)
- Test suite: tests/test_auth_public_profile.py (public profile endpoint tests)

### Recommendation Architecture
- **Movie seed pipeline** (import_data domain):
  1. Download TMDB daily export (`https://files.tmdb.org/p/exports/movie_ids_MM_DD_YYYY.json.gz`) — no auth needed
  2. Filter to `popularity > threshold` and `adult=false` (~10-50K movies)
  3. Fetch full details per movie via TMDB API (`/movie/{id}?append_to_response=credits,videos`) — concurrent (20 in-flight via semaphore, 500-movie chunks, retry on 429)
  4. Cache in `movies` table via SQLAlchemy
  5. Embed overviews with OpenAI `text-embedding-3-small` → store in `movie_embeddings` table
- **Taste embeddings** (`compute_taste_embeddings()` in `app/recommendations/services.py`):
  - **Positive embedding**: rating-weighted average of movies at/above the user's 20th percentile rating (weight = rating value, 0.5–5.0). If <10 rated movies, all movies go into positive (sample too small for split).
  - **Negative embedding**: two sources merged with weighted average — (1) movies below 20th percentile rating, weighted by `MAX_RATING - rating` (0.5-star → weight 4.5); (2) explicitly hidden movies (uniform weight 1.0). Requires 10+ rated movies for rating-derived negatives.
  - Both embeddings persisted on Profile model
- **Shared 4-step pipeline** (`app/recommendations/pipeline.py`):
  - `RecommendationContext` dataclass holds all inputs (embeddings, exclusions, signal context, genre watch counts)
  - Used by both `get_recommendations()` (user) and `get_group_recommendations()` (group)
  - **Step 1**: pgvector candidate generation (500 items) + quality filter (vote_average >= 1.0) + re-ranking with negative penalty
  - **Step 2**: Softmax probabilistic sampling (500→200, temp=1.0) + tier shuffle
  - **Step 3**: Exploration scoring on high-rated DB movies (genre novelty + consensus + trending)
  - **Step 4**: Exploration sampling (temp=1.5) + blending (85% algo / 15% exploration)
- **Re-ranking** (`app/recommendations/ranking.py`): `final_score = 0.50*cosine + 0.20*genre + 0.20*consensus + 0.05*director + 0.05*cast - 0.15*negative_cosine`, clamped ≥ 0
- **Exploration scoring**: `0.50*genre_novelty + 0.40*consensus + 0.10*trending`. Genre novelty = 1 - max familiarity of movie's genres. Trending = recency by release year. Scores rescaled to P25-P75 of main algorithm scores.
- **Score scaling**: `to_match_percentage(score) = min(score + MATCH_BOOST, 1.0)` (MATCH_BOOST=0.33). Applied to all score outputs.
- **Hidden movies**: `hidden_movies` table, excluded from candidate pool. Contributes to negative embedding (merged with low-rated movie negatives). CRUD: POST/DELETE /recommendations/{tmdb_id}/hide, GET /recommendations/hidden
- **Auto-refresh triggers**: rating changes trigger rebuild only if user has <50 rated movies. Genre updates always trigger rebuild. Users with 50+ ratings use manual POST /recommendations/me/refresh.
- **Group context**: averages members' positive + negative embeddings, union of watched + hidden IDs, combined genre watch counts for exploration
- **Source tracking**: `source` column on watched_movies/watchlist_movies tracks origin
- **Ongoing sync**: TMDB Changes API for daily updates to cached movies
- **On-demand caching**: Movies found via search/Letterboxd import also get cached + embedded
- **Match scores**: `compute_match_scores()` in `movies/services.py` — applies full ranking formula including negative penalty

### Next Steps
- [x] Build tracking domain: watch/rate/review CRUD
- [x] Build movie seed pipeline: TMDB bulk export → fetch details → embed → store
- [x] Build import_data domain: Letterboxd CSV parser + workflow
- [x] Build recommendations domain: taste vectors from user ratings + similarity search via match_movies RPC
- [x] Build friends domain: request/accept/reject/list
- [x] Build groups domain: CRUD + group recommendations + group watchlists
- [x] Build watchlist system: standalone watchlists shared by users and groups
- [x] Add recommendation re-ranking layer (genre, consensus, director, cast signals)
- [x] Add recommendation source tracking (`source` column on watched/watchlist movies)

---
- **Rating scale**: 0.5–5.0 in 0.5 increments (enforced by DB check constraint on watched_movies)
- **TMDB vote_average**: stored as raw 0–10 in DB, scaled to 0–5 (÷2, 1 decimal) in MovieResponse via Pydantic field_validator. Ranking code uses raw DB value.

### Future: Algorithm Feedback Loop
- **You cannot fine-tune OpenAI embedding models** — their weights are frozen
- **Linear adapter** (near-term, once we have data): train a small 1536x1536 matrix that re-projects embeddings using (positive, negative) pairs from user ratings. LlamaIndex has an open-source implementation. Trains on CPU in minutes with ~500 examples.
- **Collaborative filtering** (medium-term, 50+ users): `implicit` library alternating least squares matrix factorization on user-item interactions. Train weekly as batch job, blend CF scores with content-based scores.
- **Learning to Rank** (long-term, 500+ rating triples): XGBoost with `rank:ndcg` objective. Features: cosine similarity, genre overlap, director match, vote_average, user avg rating. Scores 200 candidates in microseconds.
- **Key metrics to track with `source` column**: positive rate (recs rated >= 4 / total recs tracked), watchlist add rate, intra-list diversity
- **Recency weighting**: optionally weight more recent ratings higher in the average embedding
- **Random offset into candidate pool**: ~~over-fetch more candidates and sample with quality-weighted probability~~ **DONE** — implemented as softmax probabilistic sampling (500→200) in `ranking.py`

- [x] Add match_score to trending + detail endpoints
- [x] Username validation + uniqueness checks (signup + profile update)
- [x] User search endpoint (GET /auth/users/search?q=)
- [x] PATCH /groups/{group_id} (update group name)
- [x] Auto-remove from watchlist on track
- [x] Match score upward compression scaling
- [x] Rate limiting via slowapi (per-user keying from JWT, tiered limits: heavy/import/refresh/search/default)
- [x] Smart taste rebuild: skip rebuild if new rating wouldn't affect top 25 movies
- [x] Recommendation variety: shuffle within score tiers (TIER_THRESHOLD=0.02) so same-quality recs appear in different order each request
- [x] TMDB Changes API sync (POST /import/sync-movies — polls changes, upserts cached movies, re-embeds on overview change)
- [x] Probabilistic recommendation sampling: softmax-weighted 500→200 candidate selection for fresh results each request
- [x] Top-rated movies endpoint (GET /movies/top-rated — TMDB top_rated with match_score)
- [x] Avatar upload support (Supabase Storage bucket + PATCH /auth/profile accepts avatar_url)
- [x] Auth refresh endpoint (POST /auth/refresh — no JWT required)
- [x] Negative ratings affect algorithm (40th percentile split, z-score weighting, negative embedding penalty)
- [x] "Don't Show This" / hidden movies (POST/DELETE /recommendations/{tmdb_id}/hide, GET /recommendations/hidden)
- [x] Shared 4-step recommendation pipeline (pipeline.py — used by both user and group recs)
- [x] 15% exploration slots (genre novelty + consensus + trending, rescaled scores)
- [x] Refactored auto-rebuild: <50 ratings = auto-rebuild on changes, 50+ = manual refresh only

- [x] Fix recommendation quality: rating-weighted taste embedding + quality filter on candidates
- [x] Public profile endpoints (friendship-gated stats, watched movies, friends list)
- [x] Account deletion (DELETE /auth/account — full cascade cleanup)
- [x] DB connection pooling + TMDB client lifespan management
- [x] JSON structured logging
- [x] Negative embedding from low-rated movies (20th percentile split, 10+ movies required)
- [x] Password validation on signup

*Last updated: 2026-03-19*
