# TMDB Changes API Sync Plan

## Context

Cached movie data in the `movies` table goes stale — trailers get added, ratings change, cast/crew updates land. TMDB provides a Changes API (`GET /movie/changes`) that returns IDs of movies modified in a date range (max 14 days). This feature polls that API and updates only movies we've already cached.

---

## Migration

`supabase migration new add_sync_state` → SQL:
```sql
CREATE TABLE sync_state (
    key text PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz DEFAULT now()
);
```

Simple key-value store. The key we use: `"last_movie_sync_date"` with value like `"2026-03-07"`.

---

## Modified Files

### `app/import_data/models.py` — add SyncState model

```python
class SyncState(Base):
    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
```

### `app/import_data/services.py` — three changes

**1. Modify `_cache_movie()` for upsert (line 214):**

- Add optional `existing_movie: Movie | None = None` parameter
- If `existing_movie` provided: update its fields in-place, set `cached_at = now(UTC)`, skip `db.add()`
- Return `(movie, overview_changed: bool)` — compare old vs new overview
- If `existing_movie` is None: behave as today (create new Movie, `db.add()`)
- Backward compatible — `fetch_and_cache_movies()` still calls with no `existing_movie`

**2. Add `fetch_tmdb_changes()`:**

```python
async def fetch_tmdb_changes(
    start_date: str, end_date: str, tmdb_api_key: str
) -> list[int]:
```

- Calls `GET https://api.themoviedb.org/3/movie/changes?start_date=...&end_date=...&page=N`
- Paginates through all pages (response has `total_pages`)
- Filters `adult == False`
- Returns deduplicated list of tmdb_ids

**3. Add `run_sync_pipeline()`:**

```python
async def run_sync_pipeline(
    db: Session, tmdb_api_key: str, openai_client: OpenAI
) -> dict:
```

Logic:
1. Read `last_movie_sync_date` from `sync_state` table. Default: 7 days ago if missing.
2. Compute `start_date` = last sync + 1 day, `end_date` = today. Skip if already synced today. Clamp range to 14 days max (TMDB limit).
3. Call `fetch_tmdb_changes()` → list of changed IDs.
4. Filter to IDs already in our `movies` table: `db.query(Movie).filter(Movie.tmdb_id.in_(changed_ids)).all()` → build `{tmdb_id: Movie}` map.
5. Fetch fresh TMDB data concurrently — reuse existing Semaphore(20) + 500-movie chunks + 429 retry pattern from `fetch_and_cache_movies`.
6. For each response, call `_cache_movie(tmdb_data, db, existing_movie=existing, commit=False)`.
7. Collect tmdb_ids where `overview_changed == True`.
8. Batch commit updates.
9. For changed-overview movies: delete their `movie_embeddings` rows, then call `embed_movies()` (which picks up movies without embeddings).
10. Upsert `sync_state`: `key="last_movie_sync_date"`, `value=end_date`.
11. Return `{"updated": N, "re_embedded": M, "errors": E}`.

### `app/import_data/views.py` — add endpoint

```python
async def _run_sync_pipeline_async() -> None:
    db = SessionLocal()
    try:
        await services.run_sync_pipeline(db, settings.tmdb_api_key, openai_client)
    except Exception:
        logger.exception("Sync pipeline failed")
    finally:
        db.close()

@router.post("/sync-movies", status_code=status.HTTP_202_ACCEPTED)
async def sync_movies(_user_id: str = Depends(get_current_user)):
    asyncio.ensure_future(_run_sync_pipeline_async())
    return {"status": "started"}
```

Follows exact same pattern as existing `_run_seed_pipeline_async` (manual `SessionLocal()` + try/finally/close).

---

## Key Patterns Reused

| Pattern | Source | Usage |
|---------|--------|-------|
| Concurrent TMDB fetch | `fetch_and_cache_movies()` lines 58-134 | Same Semaphore(20) + chunks + 429 retry |
| Movie parsing | `_cache_movie()` lines 214-266 | Extended for upsert |
| Background task | `_run_seed_pipeline_async()` lines 18-27 | Same asyncio.ensure_future pattern |
| Embedding | `embed_movies()` lines 140-195 | Called after deleting stale embeddings |

---

## Verification

1. `supabase db push` — migration applies cleanly
2. `uvicorn main:app --reload` — starts clean
3. `POST /import/sync-movies` with JWT → 202 `{"status": "started"}`
4. Check server logs for sync progress (updated/errors/re_embedded counts)
5. Verify `sync_state` table has row: `key = "last_movie_sync_date"`
6. Call again immediately → should return early (already synced today)
7. Spot-check updated movies: query `movies` table, compare `cached_at` timestamps
