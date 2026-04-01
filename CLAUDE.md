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
- Migrations (17 total in `supabase/migrations/`):
  - Initial schema: profiles, movies, watched_movies, friendships, groups, group_members, movie_embeddings, pgvector, match_movies RPC
  - Taste profile fields on profiles, trailer_url/detail fields on movies, liked on watched_movies
  - Standalone watchlists table, watchlist_id on profiles/groups, watchlist_movies with watchlist_id FK
  - Source column on watched_movies/watchlist_movies, sync_state table
  - Negative embedding + hidden_movies, vote_count on movies
  - Apple refresh token on profiles, performance indexes, remote schema sync
  - actions_since_rebuild counter on profiles (debounced taste rebuild every 5 actions)
- Auth domain: fully implemented
  - Models: Profile (taste fields, apple_refresh_token)
  - Schemas: signup/login/refresh/profile, OAuth, onboarding, genre taste, public profile
  - Username validation: 3–30 chars, alphanumeric + periods + underscores, no leading/trailing/consecutive special chars, auto-lowercased, uniqueness check
  - Password validation: min 8 chars, at least 1 uppercase letter
  - OAuth: POST /auth/oauth — Apple Sign In via Supabase Auth (id_token + nonce + optional authorization_code)
  - Onboarding: POST /auth/complete-onboarding — sets username, display_name, favorite_genres, optional rated_movies + apple_refresh_token; triggers background taste rebuild
  - Genre taste: GET /auth/me/taste — returns genre scores with watch counts and avg ratings
  - User search: GET /auth/users/search?q= — prefix search (ILIKE) for friend autocomplete, excludes current user, returns up to 10 results
  - Avatar upload: Supabase Storage `avatars` bucket (public), RLS policies, frontend uploads to `avatars/{user_id}/avatar.png`
  - Password reset: POST /auth/forgot-password (constant response, no auth), POST /auth/reset-password (requires JWT)
  - Auth refresh: POST /auth/refresh (accepts refresh_token, no JWT required)
  - Public profile endpoints (friendship-gated via `assert_are_friends`):
    - GET /auth/users/{id}/profile — stats (watched_count, friends_count, blends_count)
    - GET /auth/users/{id}/watched — paginated watched movies
    - GET /auth/users/{id}/friends — friends list
  - Account deletion: DELETE /auth/account — full cascade cleanup (transfers group ownership, nulls watchlist_movies.added_by, cascade deletes profile/watched/friendships/hidden, deletes personal watchlist, revokes Apple refresh token, best-effort Supabase Auth + avatar cleanup via `supabase_admin`)
- Movies domain: fully implemented
  - Model: Movie (SQLAlchemy, includes director, cast, tagline, backdrop_path, imdb_id)
  - Schemas: MovieResponse (all fields including credits, vote_average scaled from TMDB 0-10 to 0-5 via Pydantic validator), MovieSearchResult
  - Services: TMDB search, movie detail fetch with DB caching (uses append_to_response=credits,videos for single API call), `compute_match_scores()` batch-computes personalized scores for any list of tmdb_ids, `enrich_from_cache()` merges cached movie details (trailer, cast, director, runtime, tagline, backdrop) into list responses, `cache_movies_in_background()` async background task fetches + caches uncached movies after response
  - Browse endpoints with softmax sampling (`app/movies/sampling.py`): over-fetches 5 TMDB pages concurrently, deduplicates, softmax-samples 20 results weighted by vote_average (temp=1.2). Supports `exclude` query param (comma-separated tmdb_ids) for infinite scroll. Results enriched from DB cache (hybrid: cached movies get full detail, uncached get basic fields + background task to cache).
  - Views: GET /movies/trending (weekly trending + match_score), GET /movies/top-rated (top rated + match_score), GET /movies/discover?genres= (genre-filtered discovery, optional auth via `get_optional_user`, vote_avg >= 6.0), GET /movies/search (TMDB search), GET /movies/{tmdb_id} (cached detail + trailer + credits + match_score)
  - `match_score` = same ranking formula as recommendations (0.50*cosine + 0.20*genre + 0.20*consensus + 0.05*director + 0.05*cast), null if user has no taste profile
  - All endpoints require JWT auth except discover (optional)
- TMDB client lifecycle: FastAPI lifespan context manager in main.py (httpx.AsyncClient with connection pooling: max_connections=100, max_keepalive=20, timeout=30s). Stored on `app.state.tmdb_client`, accessed via `get_tmdb_client` dependency.
- All domain routers registered in main.py
- DB connection pooling: `pool_recycle=1800`, `pool_pre_ping=True` on SQLAlchemy engine
- JSON structured logging via python-json-logger (stdout, with timestamp/level/name/message fields)
- Tracking domain: fully implemented
  - Model: WatchedMovie (SQLAlchemy, matches watched_movies table with unique(user_id, tmdb_id))
  - Schemas: TrackMovieRequest (with source field), UpdateTrackingRequest, WatchedMovieResponse (with liked field), WatchHistoryResponse, FriendWatchedResponse, FriendsWhoWatchedResponse
  - Services: track_movie (upsert, auto-caches movie via TMDB), get_watch_history (paginated, joined with movies), get_watched_movie, update_watched_movie, delete_watched_movie, get_friends_who_watched
  - Views: POST /tracking/ (track/upsert), GET /tracking/ (paginated history), GET /tracking/{tmdb_id}, PATCH /tracking/{tmdb_id}, DELETE /tracking/{tmdb_id}, GET /tracking/{tmdb_id}/friends (friends who watched this movie with their ratings/reviews)
  - All endpoints require JWT auth; POST auto-caches movie from TMDB if not in DB
  - Tracking a movie auto-removes it from the user's personal watchlist (if present)
  - Debounced taste rebuild: every 5 user actions (rate/hide/watchlist) triggers background rebuild via BackgroundTasks
- Friends domain: fully implemented
  - Model: Friendship (SQLAlchemy, matches friendships table with unique(requester_id, addressee_id))
  - Schemas: SendFriendRequestRequest, FriendResponse (includes friendship_id for delete), FriendRequestResponse, FriendListResponse, PendingRequestsResponse
  - Services: send_friend_request (by username, prevents self-friending, allows re-request after rejection), accept/reject (addressee only), get_friends (accepted, either party), get_pending_requests (split incoming/outgoing), remove_friend (either party)
  - Views: POST /friends/request, POST /friends/{id}/accept, POST /friends/{id}/reject, GET /friends/, GET /friends/requests, DELETE /friends/{id}
  - All endpoints require JWT auth
- Movie seed pipeline (import_data domain): fully implemented
  - Model: MovieEmbedding (SQLAlchemy, maps to existing movie_embeddings table)
  - Schemas: SeedStatusResponse
  - Services: download_tmdb_export (daily JSONL, all non-adult movies), fetch_and_cache_movies (concurrent via asyncio.Semaphore(20) + gather, 500-movie chunks, retry on 429, batch commits, skips existing, includes credits+videos), embed_movies (OpenAI text-embedding-3-small, batch 2000), run_seed_pipeline (orchestrator)
  - Views: POST /import/seed-movies (BackgroundTask, returns 202)
  - Pipeline is idempotent — safe to re-run, skips already cached/embedded movies
  - Uses `asyncio.ensure_future()` instead of `BackgroundTasks` (avoids `asyncio.run()` inside existing event loop)
- Letterboxd import (import_data domain): fully implemented
  - Schemas: FilmRecord (parsed film from CSV), ImportSummaryResponse
  - Workflows: run_letterboxd_import — parses zip of 5 CSVs (watched, ratings, reviews, likes, watchlist), deduplicates by Letterboxd URI, resolves TMDB IDs via fuzzy title match, caches movies, writes WatchedMovie + WatchlistMovie entries, single batch commit
  - Views: POST /import/letterboxd (file upload, returns import summary)
  - Per-movie error isolation — one failure doesn't abort the import
- Watchlist system: fully implemented
  - Models: Watchlist, WatchlistMovie (watchlist_id + tmdb_id + added_by)
  - Schemas: AddToWatchlistRequest (with source field), WatchlistMovieResponse (with match_score), WatchlistResponse, WatchlistStatusResponse
  - Services: get_watchlist (paginated), add_to_watchlist (auto-cache from TMDB), remove_from_watchlist
  - Views: GET/POST/DELETE /watchlist/ (personal, own router), GET/POST/DELETE /groups/{id}/watchlist (group)
  - Signup auto-creates a personal watchlist for each new user
- Groups domain: fully implemented
  - Models: Group (id, name, created_by, watchlist_id), GroupMember (composite PK: group_id + user_id)
  - Schemas: CreateGroupRequest, UpdateGroupRequest, AddMemberRequest, GroupMemberResponse, GroupResponse, GroupDetailResponse, GroupListResponse, GroupRecMovieResponse, GroupRecommendationsResponse
  - Services: create_group (with linked watchlist), list_groups, get_group, update_group (creator only), add_member (by username, 10-member cap), kick_member (can't kick owner), leave_group (transfers ownership), delete_group (creator only, cascade)
  - Views: POST /groups/, GET /groups/, GET /groups/{id}, PATCH /groups/{id} (update name, creator only), DELETE /groups/{id}, POST /groups/{id}/members, POST /groups/{id}/members/{uid}/kick, POST /groups/{id}/leave, GET /groups/{id}/recommendations, GET/POST/DELETE /groups/{id}/watchlist
  - Group recommendations: uses shared 4-step pipeline — averages members' positive + negative embeddings, excludes union of all members' watched + hidden movies, combined genre watch counts for exploration
- Recommendations domain: fully implemented
  - Schemas: FeedRequest, RecommendedMovieResponse, RecommendationsResponse, HiddenMovieResponse, HiddenMoviesListResponse
  - Services: `compute_taste_embeddings()` uses 20th percentile split — positive embedding from movies at/above threshold (rating-weighted), negative from movies below threshold (weighted by MAX_RATING - rating) merged with hidden movie embeddings. Requires 10+ rated movies for rating-derived negatives.
  - Shared 4-step pipeline (`app/recommendations/pipeline.py`): used by both user and group recs
    - Step 1: pgvector candidate generation (500 items) + quality filter (vote_average >= 1.0) + re-ranking with negative penalty
    - Step 2: Softmax probabilistic sampling (500→200) + tier shuffle
    - Step 3: Exploration scoring (genre novelty + consensus + trending) on high-rated DB movies
    - Step 4: Exploration sampling + blending (85% algo / 15% exploration per page)
  - Re-ranking formula: `0.50*cosine + 0.20*genre + 0.20*consensus + 0.05*director + 0.05*cast - 0.15*negative_cosine`, clamped ≥ 0
  - Views: GET /recommendations/me (limit up to 200), POST /recommendations/me/feed (infinite scroll — accepts `exclude` list of seen tmdb_ids + `limit`), POST /recommendations/me/refresh, POST /recommendations/{tmdb_id}/hide, DELETE /recommendations/{tmdb_id}/hide, GET /recommendations/hidden
  - Hidden movies: HiddenMovie model, excluded from recs. Hidden movies contribute to negative embedding (merged with low-rated movie negatives).
  - Debounced taste rebuild: `actions_since_rebuild` counter on profiles, triggers background rebuild every 5 actions (rate/hide/watchlist). Genre updates via PATCH /auth/profile still trigger immediate background rebuild. Manual refresh via POST /recommendations/me/refresh always rebuilds.
  - Exploration picks: movies from underrepresented genres with high vote_average, scored by `0.50*novelty + 0.40*consensus + 0.10*trending`, rescaled to P25-P75 of main scores
- TMDB Changes API sync: `POST /import/sync-movies` polls TMDB Changes API for movies modified since last sync, updates cached movies in-place, re-embeds on overview change. Uses `sync_state` table. Rate-limited to 1/day.
- JWT verification: local JWKS-based validation via PyJWKClient (ES256/HS256, audience=authenticated, 1h cache)
- `supabase_admin` client in dependencies.py (service role key, for admin operations like deleting auth users, revoking Apple tokens)
- `get_optional_user` dependency: extracts user ID from Bearer token if present, returns None otherwise (for optional auth endpoints)
- Match score scaling: `to_match_percentage()` in `ranking.py` adds flat MATCH_BOOST (0.33) to raw score, capped at 1.0. Applied to all score outputs.
- Rate limiting: slowapi with per-user keying (JWT sub claim, fallback to IP). Tiered limits: LIMIT_HEAVY (1/day) for seed/sync, LIMIT_IMPORT (3/hour) for letterboxd, LIMIT_REFRESH (5/hour) for rec refresh, LIMIT_SEARCH (30/min) for search/discover, LIMIT_DEFAULT (60/min) for everything else. Disabled in tests via TESTING=true. Config in `app/core/rate_limit.py`.
- Test suite: tests/test_auth_public_profile.py (public profile endpoint tests)

### Recommendation Architecture
- **Movie seed pipeline** (import_data domain):
  1. Download TMDB daily export (`https://files.tmdb.org/p/exports/movie_ids_MM_DD_YYYY.json.gz`) — no auth needed
  2. Filter to `popularity > threshold` and `adult=false` (~10-50K movies)
  3. Fetch full details per movie via TMDB API (`/movie/{id}?append_to_response=credits,videos`) — concurrent (20 in-flight via semaphore, 500-movie chunks, retry on 429)
  4. Cache in `movies` table via SQLAlchemy
  5. Embed overviews with OpenAI `text-embedding-3-small` → store in `movie_embeddings` table
- **Taste embeddings** (`compute_taste_embeddings()` in `app/recommendations/services.py`):
  - **Positive embedding**: rating-weighted average of movies at/above the user's 20th percentile rating (weight = rating value, 0.5–5.0), blended with watchlist movie embeddings (weight = 1.5 per movie). If <10 rated movies, all movies go into positive (sample too small for split). Watchlist blend is proportional — rated movies' total weight vs watchlist total weight, so watchlist nudges direction without dominating.
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
- **Watchlist exclusion**: personal recs exclude user's watchlist movies; group recs exclude group's shared watchlist movies. Watchlist movies are already queued to watch — no need to recommend them again.
- **Debounced taste rebuild**: `actions_since_rebuild` counter on profiles increments on rate/hide/watchlist actions. Every 5 actions (`REBUILD_ACTION_INTERVAL`), triggers a background `rebuild_taste_profile()` via FastAPI `BackgroundTasks` and resets counter to 0. Wired into POST /tracking/, POST /recommendations/{id}/hide, POST /watchlist/. Genre updates via PATCH /auth/profile still trigger immediate background rebuild. Manual refresh via POST /recommendations/me/refresh always rebuilds.
- **Group context**: averages members' positive + negative embeddings, union of watched + hidden + group watchlist IDs, combined genre watch counts for exploration
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
- [x] Apple Sign In (OAuth endpoint, Apple token infrastructure)
- [x] Onboarding flow (POST /auth/complete-onboarding with username, genres, rated movies)
- [x] Genre taste endpoint (GET /auth/me/taste)
- [x] Discover endpoint (GET /movies/discover?genres= with optional auth)
- [x] Infinite scroll / feed endpoint (POST /recommendations/me/feed with exclude list)
- [x] Softmax sampling on browse endpoints (trending, top-rated, discover)
- [x] Friends who watched (GET /tracking/{tmdb_id}/friends)
- [x] Apple token revocation on account deletion
- [x] Local JWKS-based JWT verification (replaced Supabase SDK get_user calls)
- [x] Debounced taste rebuild every 5 actions (rate/hide/watchlist) via BackgroundTasks
- [x] N+1 query optimization: batch fetch profiles in friends list, pending requests, public friends, group recommendations
- [x] Eliminate duplicate profile fetch in recommendation pipeline (pass through instead of re-query)
- [x] Defer Movie.cast JSONB on exploration pool query (not needed for scoring)
- [x] Group recommendations: single profile batch + single top movies query + inline genre counting (was 3 loops × N members)
- [x] Bump watch history + watchlist limit to 500 (for iOS bootstrap cache)
- [x] POST /groups/{id}/recommendations/feed with exclude list for infinite scroll
- [x] Pydantic models on all endpoints: MessageResponse, SeedStatusResponse, UpdateProfileRequest/UpdateGroupRequest passed directly
- [x] Exclude watchlist movies from personal and group recommendations
- [x] Blend watchlist movies into positive taste embedding (weight 1.5 per movie)
- [x] Enrich trending/top-rated/discover with cached movie details (trailer, cast, director, runtime, tagline, backdrop) + background task to cache uncached movies

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

*Last updated: 2026-04-01*
