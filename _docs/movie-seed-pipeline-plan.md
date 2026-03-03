# Movie Seed Pipeline Plan

## Context
Recommendations require movie embeddings in the DB. Currently movies only get cached on-demand (search/tracking). We need a bulk pipeline to:
1. Download TMDB's daily movie ID export
2. Filter to popular movies (~50K, popularity > 5)
3. Fetch full details from TMDB API for each
4. Cache in `movies` table
5. Embed overviews via OpenAI → store in `movie_embeddings` table

Triggered via `POST /import/seed-movies`. Runs as a background task (FastAPI `BackgroundTasks`) so the endpoint returns immediately.

## DB Schema (already exists)
```sql
-- movies table: already has SQLAlchemy model
-- movie_embeddings table: exists in DB, NO SQLAlchemy model yet
movie_embeddings:
  tmdb_id     int PK → movies(tmdb_id) on delete cascade
  embedding   vector(1536)
  created_at  timestamptz default now()
```

## Files to Create/Modify

### 1. `app/import_data/models.py` (new)
`MovieEmbedding` SQLAlchemy model — maps to existing `movie_embeddings` table.
- tmdb_id (int, PK), embedding (Vector(1536)), created_at

### 2. `app/import_data/schemas.py` (new)
- `SeedStatusResponse`: status message, counts (total_ids, fetched, embedded, skipped, errors)

### 3. `app/import_data/services.py` (new)
Three pipeline steps as functions. Each is resumable — skips movies/embeddings already in DB.

**Step 1: `download_tmdb_export()`**
- GET `https://files.tmdb.org/p/exports/movie_ids_{MM}_{DD}_{YYYY}.json.gz` (no auth needed)
- Decompress gzip, parse JSONL (one JSON object per line)
- Filter: `popularity > 5` and `adult == false`
- Return list of tmdb_ids
- Note: export is from previous day, so use yesterday's date

**Step 2: `fetch_and_cache_movies(tmdb_ids, db, tmdb_client)`**
- For each tmdb_id not already in `movies` table:
  - Fetch from TMDB API via `GET /movie/{id}?append_to_response=videos`
  - Reuse `app/movies/services._cache_movie_from_tmdb()` pattern (extract to shared util or duplicate the small parser)
  - Rate limit: ~40 req/s — use `asyncio.sleep(0.025)` between requests
  - Batch commit every 100 movies
  - Log progress every 500 movies
- Skip on 404 (movie removed from TMDB)

**Step 3: `embed_movies(db, openai_client)`**
- Query movies that have an overview but no row in `movie_embeddings`
- Batch embed via OpenAI `text-embedding-3-small` (batch size 100, max 8191 tokens per input)
- Embed text: `"{title} ({year}): {overview}"` — gives embedding more context than overview alone
- Bulk insert embeddings into `movie_embeddings`
- Batch commit every 100

**Orchestrator: `run_seed_pipeline(db, tmdb_client, openai_client)`**
- Calls steps 1 → 2 → 3 sequentially
- Logs progress to stdout (visible in server logs)
- Returns summary dict with counts

### 4. `app/import_data/views.py` (modify existing stub)
- Replace letterboxd stub with:

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| `POST /import/seed-movies` | Kicks off pipeline as BackgroundTask | 202 `{"status": "started"}` |

- Uses `BackgroundTasks` so endpoint returns immediately
- Requires JWT auth (admin-only in practice, but just auth-gated for now)
- Injects `get_db`, `get_tmdb_client`, `openai_client` from dependencies

### Key Reuse
- `app/movies/models.Movie` — check which movies already cached
- `app/movies/services._cache_movie_from_tmdb()` logic — parse TMDB response into Movie row (will extract the trailer fetch since bulk doesn't need trailers)
- `app/dependencies.openai_client` — already instantiated
- `app/dependencies.get_tmdb_client` — async httpx client with TMDB API key
- `app/database.SessionLocal` — for background task DB session (can't use Depends outside request)

### Important Details
- **Background task DB session**: `BackgroundTasks` runs outside the request lifecycle, so we create a `SessionLocal()` session directly instead of using `Depends(get_db)`
- **TMDB client in background**: Similarly create a fresh httpx client in the background task
- **No trailers in bulk**: Skip trailer fetching during seed (expensive extra API call per movie). Trailers get fetched on-demand when a user views a movie.
- **Idempotent**: Safe to run multiple times — skips already-cached movies and already-embedded movies

## Implementation Order
1. `models.py` (MovieEmbedding) → 2. `schemas.py` → 3. `services.py` (the bulk of the work) → 4. `views.py`

## Verification
1. `pre-commit run --all-files` — lint passes
2. `python -c "from main import app"` — server imports clean
3. `curl -X POST http://localhost:8000/import/seed-movies -H "Authorization: Bearer $TOKEN"` — returns 202
4. Check server logs for progress output
5. After pipeline completes, verify data: `SELECT count(*) FROM movies; SELECT count(*) FROM movie_embeddings;`
