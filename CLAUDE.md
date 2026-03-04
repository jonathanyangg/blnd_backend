# BLND Backend

## Tech Stack
- **Framework**: FastAPI
- **ORM**: SQLAlchemy (models + queries)
- **Migrations**: Supabase CLI (`supabase migration new`, `supabase db push`)
- **Database**: Supabase Postgres + pgvector
- **Auth**: Supabase Auth via supabase-py (JWT) — only use of supabase-py
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
- supabase-py is used ONLY for Auth (signup, login, verify JWT)
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
- Auth domain: models (Profile with taste fields), schemas (signup/login/profile + UpdateProfileRequest), services (Supabase Auth + SQLAlchemy), views
- Movies domain: fully implemented
  - Model: Movie (SQLAlchemy, includes director, cast, tagline, backdrop_path, imdb_id)
  - Schemas: MovieResponse (all fields including credits), MovieSearchResult
  - Services: TMDB search, movie detail fetch with DB caching (uses append_to_response=credits,videos for single API call)
  - Views: GET /movies/search (TMDB search), GET /movies/{tmdb_id} (cached detail + trailer + credits)
  - All endpoints require JWT auth
- TMDB client lifecycle: async generator dependency in dependencies.py (properly closes httpx client)
- All domain routers registered in main.py with stub endpoints
- FastAPI server runs clean on `uvicorn main:app --reload`
- Tracking domain: fully implemented
  - Model: WatchedMovie (SQLAlchemy, matches watched_movies table with unique(user_id, tmdb_id))
  - Schemas: TrackMovieRequest, UpdateTrackingRequest, WatchedMovieResponse, WatchHistoryResponse
  - Services: track_movie (upsert, auto-caches movie via TMDB), get_watch_history (paginated, joined with movies), get_watched_movie, update_watched_movie, delete_watched_movie
  - Views: POST /tracking/ (track/upsert), GET /tracking/ (paginated history), GET /tracking/{tmdb_id}, PATCH /tracking/{tmdb_id}, DELETE /tracking/{tmdb_id}
  - All endpoints require JWT auth; POST auto-caches movie from TMDB if not in DB
- Friends domain: fully implemented
  - Model: Friendship (SQLAlchemy, matches friendships table with unique(requester_id, addressee_id))
  - Schemas: SendFriendRequestRequest, FriendResponse (includes friendship_id for delete), FriendRequestResponse, FriendListResponse, PendingRequestsResponse
  - Services: send_friend_request (by username, prevents self-friending, allows re-request after rejection), accept/reject (addressee only), get_friends (accepted, either party), get_pending_requests (split incoming/outgoing), remove_friend (either party)
  - Views: POST /friends/request, POST /friends/{id}/accept, POST /friends/{id}/reject, GET /friends/, GET /friends/requests, DELETE /friends/{id}
  - All endpoints require JWT auth; no migrations needed (friendships table already exists)
- Movie seed pipeline (import_data domain): fully implemented
  - Model: MovieEmbedding (SQLAlchemy, maps to existing movie_embeddings table)
  - Schemas: SeedStatusResponse
  - Services: download_tmdb_export (daily JSONL, all non-adult movies), fetch_and_cache_movies (rate-limited, batch commits, skips existing, includes credits), embed_movies (OpenAI text-embedding-3-small, batch 100), run_seed_pipeline (orchestrator)
  - Views: POST /import/seed-movies (BackgroundTask, returns 202), POST /import/letterboxd (stub)
  - Pipeline is idempotent — safe to re-run, skips already cached/embedded movies
- Recommendations domain: fully implemented
  - Schemas: RecommendedMovieResponse (movie fields + similarity score), RecommendationsResponse (results + taste_bio)
  - Services: dual embedding strategy (switchable via `EMBEDDING_STRATEGY` in services.py):
    - `"average"` (current default): weighted average of user's top-rated movie embeddings from movie_embeddings table — compares apples to apples
    - `"llm"`: gpt-4o-mini generates ideal movie synopsis → embedded with text-embedding-3-small
    - Both strategies still generate taste bio via gpt-4o-mini for display
  - get_recommendations: pgvector similarity via match_movies RPC (cast to vector(1536)), excludes watched, paginated
  - Views: GET /recommendations/me (returns recs, builds taste profile on first call if needed), POST /recommendations/me/refresh (force rebuild + fresh recs)
  - Taste profile auto-rebuilds in background when: user rates/updates/deletes a tracked movie, or updates favorite_genres via PATCH /auth/profile
- Auth domain updates:
  - Added update_profile service (updates display_name/favorite_genres, detects genre changes)
  - Added PATCH /auth/profile endpoint (triggers background taste rebuild on genre change)
  - Fixed GET /auth/me to include taste_bio and favorite_genres in response

### Recommendation Architecture
- **Movie seed pipeline** (import_data domain):
  1. Download TMDB daily export (`https://files.tmdb.org/p/exports/movie_ids_MM_DD_YYYY.json.gz`) — no auth needed
  2. Filter to `popularity > threshold` and `adult=false` (~10-50K movies)
  3. Fetch full details per movie via TMDB API (`/movie/{id}?append_to_response=videos`) — rate limit ~40 req/s
  4. Cache in `movies` table via SQLAlchemy
  5. Embed overviews with OpenAI `text-embedding-3-small` → store in `movie_embeddings` table
- **Taste embedding** (switchable `EMBEDDING_STRATEGY` in `app/recommendations/services.py`):
  - `"average"` (default): weighted average of top 25 rated movie embeddings — same embedding space as movie_embeddings, higher similarity scores
  - `"llm"`: gpt-4o-mini generates ideal movie synopsis, embedded with text-embedding-3-small
  - Both still generate taste bio for display via gpt-4o-mini
- **Recommendations** = user taste embedding vs movie embeddings via `match_movies` RPC (pgvector cosine similarity, `cast(:param AS vector(1536))`)
- **Auto-refresh triggers**: rating changes (track/update/delete) and genre updates trigger background taste rebuild
- **Ongoing sync**: TMDB Changes API (`/movie/changes`) for daily updates to cached movies
- **On-demand caching**: Movies found via search/Letterboxd import also get cached + embedded

### Next Steps
- [x] Build tracking domain: watch/rate/review CRUD
- [x] Build movie seed pipeline: TMDB bulk export → fetch details → embed → store
- [ ] Build import_data domain: Letterboxd CSV parser + workflow/flow
- [x] Build recommendations domain: taste vectors from user ratings + similarity search via match_movies RPC
- [x] Build friends domain: request/accept/reject/list
- [ ] Build groups domain: CRUD + group recommendations

---
- **Rating scale**: 0.5–5.0 in 0.5 increments (enforced by DB check constraint on watched_movies)

### Future: Hybrid Search for Recommendations
The `"average"` embedding strategy works well for semantic similarity but misses explicit signals. Layer in hybrid search to boost results that match on structured metadata:
- **Genre boosting**: boost movies sharing genres with user's favorite_genres or top-rated movies' genres
- **Director boosting**: boost movies by directors the user has rated highly
- **Cast boosting**: boost movies starring actors from the user's top-rated films
- **Recency weighting**: optionally weight more recent ratings higher in the average
- Implementation approach: score = `alpha * cosine_similarity + beta * genre_overlap + gamma * director_match`. Tune weights empirically. Could be done in SQL (post-filter/re-rank) or in Python after the pgvector query returns candidates.

*Last updated: 2026-03-04*


