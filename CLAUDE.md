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
- Fifth migration pushed: remote schema sync
- Sixth migration pushed: added liked column to watched_movies
- Seventh migration pushed: created watchlist_movies table
- Eighth migration pushed: standalone watchlists table, watchlist_id on profiles/groups, recreated watchlist_movies with watchlist_id FK
- Auth domain: models (Profile with taste fields), schemas (signup/login/profile + UpdateProfileRequest), services (Supabase Auth + SQLAlchemy), views
- Movies domain: fully implemented
  - Model: Movie (SQLAlchemy, includes director, cast, tagline, backdrop_path, imdb_id)
  - Schemas: MovieResponse (all fields including credits, vote_average scaled from TMDB 0-10 to 0-5 via Pydantic validator), MovieSearchResult
  - Services: TMDB search, movie detail fetch with DB caching (uses append_to_response=credits,videos for single API call)
  - Views: GET /movies/trending (TMDB weekly trending), GET /movies/search (TMDB search), GET /movies/{tmdb_id} (cached detail + trailer + credits)
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
  - Services: download_tmdb_export (daily JSONL, all non-adult movies), fetch_and_cache_movies (concurrent via asyncio.Semaphore(40) + gather, 500-movie chunks, batch commits, skips existing, includes credits), embed_movies (OpenAI text-embedding-3-small, batch 100), run_seed_pipeline (orchestrator)
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
  - Schemas: CreateGroupRequest, AddMemberRequest, GroupMemberResponse, GroupResponse, GroupDetailResponse, GroupListResponse, GroupRecMovieResponse, GroupRecommendationsResponse
  - Services: create_group (with linked watchlist), list_groups, get_group, add_member (by username, 10-member cap), kick_member (can't kick owner), leave_group (transfers ownership), delete_group (creator only, cascade)
  - Views: POST /groups/, GET /groups/, GET /groups/{id}, DELETE /groups/{id}, POST /groups/{id}/members, POST /groups/{id}/members/{uid}/kick, POST /groups/{id}/leave, GET /groups/{id}/recommendations, GET/POST/DELETE /groups/{id}/watchlist
  - Group recommendations: averages members' top-rated movie embeddings via pgvector match_movies RPC, excludes all members' watched movies
- Tracking domain: added `liked` field to WatchedMovieResponse schema and _to_response
- Recommendations: fixed bug where average strategy never persisted taste_embedding to profile, replaced pure Python vector math with numpy
- Recommendations domain: fully implemented
  - Schemas: RecommendedMovieResponse (movie fields + similarity + score), RecommendationsResponse (results + taste_bio)
  - Services: dual embedding strategy (switchable via `EMBEDDING_STRATEGY` in services.py):
    - `"average"` (current default): weighted average of user's top-rated movie embeddings from movie_embeddings table — compares apples to apples
    - `"llm"`: gpt-4o-mini generates ideal movie synopsis → embedded with text-embedding-3-small
    - Both strategies still generate taste bio via gpt-4o-mini for display
  - get_recommendations: pgvector candidate generation (200 items) → Python re-ranking with structured signals → paginated results
  - Re-ranking layer (`app/recommendations/ranking.py`): `rerank_candidates()` scores each candidate as weighted sum of cosine_similarity (0.50), genre_overlap (0.20), consensus/vote_average (0.20), director_boost (0.05), cast_boost (0.05)
  - Views: GET /recommendations/me (returns recs, builds taste profile on first call if needed), POST /recommendations/me/refresh (force rebuild + fresh recs)
  - Taste profile auto-rebuilds in background when: user rates/updates/deletes a tracked movie, or updates favorite_genres via PATCH /auth/profile
- Ninth migration: added `source` column to watched_movies and watchlist_movies (tracks origin: 'manual', 'recommendation', 'letterboxd_import')
- Recommendation source tracking: TrackMovieRequest and AddToWatchlistRequest accept `source` field, Letterboxd import sets `source="letterboxd_import"`
- Auth domain updates:
  - Added update_profile service (updates display_name/favorite_genres, detects genre changes)
  - Added PATCH /auth/profile endpoint (triggers background taste rebuild on genre change)
  - Fixed GET /auth/me to include taste_bio and favorite_genres in response
- MovieResponse vote_average scaled from TMDB 0–10 to 0–5 via Pydantic field_validator (DB stores raw value)
- Watchlist endpoints extracted to own domain (`app/watchlist/`) at `/watchlist/` prefix (was `/tracking/watchlist`, conflicted with `/tracking/{tmdb_id}`)
- Seed pipeline TMDB fetching parallelized: asyncio.Semaphore(40) + gather in 500-movie chunks (was sequential ~40 req/s)
- OpenAPI spec auto-export: `openapi.json` written to project root on server startup via FastAPI lifespan handler (for frontend context)

### Recommendation Architecture
- **Movie seed pipeline** (import_data domain):
  1. Download TMDB daily export (`https://files.tmdb.org/p/exports/movie_ids_MM_DD_YYYY.json.gz`) — no auth needed
  2. Filter to `popularity > threshold` and `adult=false` (~10-50K movies)
  3. Fetch full details per movie via TMDB API (`/movie/{id}?append_to_response=credits`) — concurrent (40 in-flight via semaphore, 500-movie chunks)
  4. Cache in `movies` table via SQLAlchemy
  5. Embed overviews with OpenAI `text-embedding-3-small` → store in `movie_embeddings` table
- **Taste embedding** (switchable `EMBEDDING_STRATEGY` in `app/recommendations/services.py`):
  - `"average"` (default): weighted average of top 25 rated movie embeddings — same embedding space as movie_embeddings, higher similarity scores
  - `"llm"`: gpt-4o-mini generates ideal movie synopsis, embedded with text-embedding-3-small
  - Both still generate taste bio for display via gpt-4o-mini
- **Candidate generation** = user taste embedding vs movie embeddings via `match_movies` RPC (pgvector cosine similarity, `cast(:param AS vector(1536))`) — over-fetches 200 candidates
- **Re-ranking** (`app/recommendations/ranking.py`): `final_score = 0.50*cosine + 0.20*genre_jaccard + 0.20*consensus + 0.05*director + 0.05*cast`
- **Source tracking**: `source` column on watched_movies/watchlist_movies tracks where user found the movie ('manual', 'recommendation', 'letterboxd_import')
- **Auto-refresh triggers**: rating changes (track/update/delete) and genre updates trigger background taste rebuild
- **Ongoing sync**: TMDB Changes API (`/movie/changes`) for daily updates to cached movies
- **On-demand caching**: Movies found via search/Letterboxd import also get cached + embedded

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

*Last updated: 2026-03-05*



