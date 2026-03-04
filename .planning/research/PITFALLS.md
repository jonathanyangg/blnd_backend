# Pitfalls Research

**Domain:** Letterboxd CSV import — FastAPI + SQLAlchemy + TMDB
**Researched:** 2026-03-03
**Confidence:** HIGH (findings derived from direct inspection of actual Letterboxd export zip, existing codebase, and DB schema)

---

## Critical Pitfalls

### Pitfall 1: Treating CSV Files as Nested Subsets

**What goes wrong:**
The import logic reads watched.csv first, then overlays ratings, reviews, and likes onto those entries. Any movie that only appears in reviews.csv, ratings.csv, or likes/films.csv is silently dropped.

**Why it happens:**
It feels logical that "all rated films were watched" and "all reviewed films were rated." Both are false. Verified against the actual export: `A Minecraft Movie (2025)` appears in reviews.csv but is absent from both watched.csv and ratings.csv. Additionally, 11 of 16 liked films (69%) are absent from watched.csv entirely.

**How to avoid:**
Build a union, not a chain. Use Letterboxd URI as the primary key and take the union of all four sources:
```python
# Correct
merged: dict[str, MovieRecord] = {}
for row in watched_rows: merged.setdefault(row["uri"], ...).update_from_watched(row)
for row in ratings_rows: merged.setdefault(row["uri"], ...).update_from_ratings(row)
for row in reviews_rows: merged.setdefault(row["uri"], ...).update_from_reviews(row)
for row in likes_rows:   merged.setdefault(row["uri"], ...).mark_liked()

# Wrong
for row in watched_rows:
    if row["uri"] in ratings_by_uri:   # drops films with ratings but no watched entry
        ...
```

**Warning signs:**
- Import count exactly matches watched.csv row count (46 in the sample export) but the user has reviews or likes for films not in that list
- User reports "my liked films from years ago didn't import"
- A Minecraft Movie (or any recently logged film) is missing after import

**Phase to address:**
Import workflow construction phase (the first real implementation step).

---

### Pitfall 2: Using Letterboxd URI Instead of Name+Year as the TMDB Lookup Key

**What goes wrong:**
The Letterboxd URI (e.g. `https://boxd.it/lScm`) uniquely identifies a film on Letterboxd but carries no TMDB-recognizable information. Passing it to TMDB search returns zero results. The correct lookup is Name + Year against TMDB's `/search/movie` endpoint.

**Why it happens:**
The URI is the most reliable join key across CSV files, so developers naturally try to reuse it for TMDB resolution too.

**How to avoid:**
Keep the two concerns separate. Use the URI exclusively for merging CSV rows. Use Name + Year exclusively for TMDB resolution. Never pass the URI to TMDB.

**Warning signs:**
- TMDB search returning 0 results for every movie
- `search_movies()` call logs showing `query=https://boxd.it/...`

**Phase to address:**
Import workflow construction phase, in the TMDB resolution function.

---

### Pitfall 3: No Year-Based Fallback in TMDB Search

**What goes wrong:**
Searching TMDB with both `query=name` and `year=year` returns zero results for films where Letterboxd's year differs from TMDB's primary release year by even one year (festival year vs. wide release year, regional release differences). The entire movie record is skipped without any fallback.

**Why it happens:**
TMDB's `year` parameter filters strictly. Letterboxd uses the year of the user's first encounter or a regional release year. Example: a film premiering at Cannes in December 2021 may be logged as 2021 on Letterboxd but listed as 2022 on TMDB.

**How to avoid:**
Implement a two-step resolution:
```python
async def resolve_tmdb_id(name: str, year: str, client) -> int | None:
    # Step 1: search with year — fast and usually correct
    results = await tmdb_search(name, year=year, client=client)
    if results:
        # verify year is within ±1 to avoid wrong-year false positives
        for r in results:
            if abs((r.get("year") or 0) - int(year)) <= 1:
                return r["tmdb_id"]

    # Step 2: search without year — broader, pick best title match
    results = await tmdb_search(name, client=client)
    if results:
        return results[0]["tmdb_id"]

    return None  # unresolvable — skip and log
```

**Warning signs:**
- Any arthouse, foreign-language, or festival film returns zero results
- Import resolution rate below ~90% on a typical Letterboxd export
- Log shows films from the 2020s failing to resolve

**Phase to address:**
Import workflow construction phase, `resolve_tmdb_id` helper function.

---

### Pitfall 4: TMDB Popularity Bias Selecting the Wrong Film on Ambiguous Titles

**What goes wrong:**
TMDB returns results sorted by popularity, not by year-relevance. For ambiguous titles — remakes, films sharing a title with a franchise entry, or titles with a more popular sequel — the first result is the wrong film.

**Why it happens:**
The existing `search_movies()` service takes the first result without year validation. That works fine for user-typed interactive searches where the user can see and choose. It breaks for automated resolution where there is no human in the loop.

Concrete examples from the actual export:
- `Monster` (2023, Japanese Kore-eda film) vs. `Monster` (2003, Aileen Wuornos biopic) — very different popularity scores
- `Doctor Strange` would return the main film but could collide with `Doctor Strange in the Multiverse of Madness` on partial match

**How to avoid:**
After receiving TMDB results, score each result:
```python
def best_match(results: list[dict], lb_year: int) -> dict | None:
    for r in results:
        tmdb_year = r.get("year")
        if tmdb_year and abs(tmdb_year - lb_year) <= 1:
            return r  # first result with matching year wins
    return None  # no year match — caller decides whether to take results[0]
```
Do not blindly return `results[0]`.

**Warning signs:**
- User reports a film imported as the wrong movie
- A 1980s film's data shows a modern remake's poster
- High mismatch rate on titles with sequels (Spider-Man, Doctor Strange)

**Phase to address:**
Import workflow construction phase, within the TMDB resolution logic.

---

### Pitfall 5: SQLAlchemy Session Left in Invalid State After Mid-Loop Exception

**What goes wrong:**
If a TMDB call raises an exception partway through the import loop, SQLAlchemy's session enters a "transaction rolled back" state. Every subsequent DB operation in the same session fails with `InvalidRequestError: Can't reconnect until invalid transaction is rolled back`. The result: the first failed movie corrupts all remaining imports in the batch.

**Why it happens:**
`get_movie_details()` calls `db.commit()` internally. If a `raise_for_status()` on TMDB throws between a `db.add()` and a `db.commit()`, or if a DB constraint fires, the session is poisoned unless explicitly rolled back.

**How to avoid:**
Wrap each movie's import in a try/except with explicit rollback on failure:
```python
for uri, record in merged.items():
    try:
        await import_single_movie(record, user_id, db, tmdb_client)
        imported_count += 1
    except Exception as e:
        db.rollback()  # mandatory — clears invalid session state
        failed.append({"name": record.name, "reason": str(e)})
        continue  # move to next movie
```
Never let an exception in one movie abort the entire import.

**Warning signs:**
- `InvalidRequestError: Can't reconnect until invalid transaction is rolled back` in logs
- Import stops entirely after first TMDB failure rather than skipping the failed movie
- Import result shows 0 movies after a partial failure

**Phase to address:**
Import workflow construction phase; the per-movie error handling must be built-in from the start, not added later.

---

### Pitfall 6: Committing Inside the Per-Movie Loop

**What goes wrong:**
Calling `db.commit()` once per movie results in N round trips to Postgres for an N-movie import. A 1000-movie import issues 1000+ commits. At Supabase's connection latency this adds several seconds and puts unnecessary load on the connection pool.

**Why it happens:**
The existing `track_movie()` service calls `db.commit()` and `db.refresh()` for interactive use where immediate consistency is expected. Reusing that service in a bulk loop inherits those per-record commits.

**How to avoid:**
Use `db.flush()` to write each row to the transaction without committing, then issue a single `db.commit()` after all rows are processed:
```python
for record in batch:
    entry = WatchedMovie(...)
    db.add(entry)
    db.flush()          # write to transaction, no commit

db.commit()             # single commit for entire batch
```
Note: `db.refresh()` requires a commit, so defer refreshes until after the final commit or skip them entirely in import context (you don't need the refreshed objects).

**Warning signs:**
- Import of 100 movies takes noticeably longer than expected
- DB connection pool exhaustion under concurrent imports
- Profiler shows N commits for N movies

**Phase to address:**
Import workflow construction phase. Do not reuse `track_movie()` as-is for bulk operations.

---

### Pitfall 7: Liked Films Require New WatchedMovie Rows, Not Just Flag Updates

**What goes wrong:**
The import sets `liked=True` only on existing `watched_movies` rows. But 69% of liked films in a typical export have no corresponding entry in `watched.csv`. The import silently skips setting the `liked` flag for those films.

**Why it happens:**
PROJECT.md describes: "Import liked films by setting liked=true on corresponding watched_movies entries." This reads as an update operation. But 11 of 16 liked films in the actual export are absent from `watched.csv`, meaning there is no row to update.

**How to avoid:**
When processing a liked film, check if a `watched_movies` row exists for that `(user_id, tmdb_id)`. If not, create one with `liked=True` and null `rating`, `review`, and `watched_date`. This is valid — all those columns are nullable in the schema.

**Warning signs:**
- `liked` count in import result equals `(liked films in watched.csv)` not `(total liked films)`
- User reports "I liked 16 films but only 5 show as liked after import"
- Liked-only films silently absent from import result

**Phase to address:**
Import workflow construction phase; specifically the liked films processing step.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Reuse `track_movie()` service for each import row | Less code to write | N commits, N TMDB fetches even if already cached, no bulk optimization | Never — write a dedicated bulk path |
| Skip TMDB year fallback (use `year=` param only) | Simpler code | ~5-10% of films silently unresolved for typical exports | Never — fallback is 5 lines |
| Use `watched.csv` Date as `watched_date` directly | No special handling | All bulk-imported historical entries show same date (mass import artifact) | Acceptable for MVP if documented |
| Skip per-movie try/except | Simpler loop | One TMDB failure aborts entire import | Never — always wrap per-movie |
| `db.extractall()` for zip extraction | Convenient | Path traversal vulnerability | Never — always read named entries |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| TMDB `/search/movie` | Pass `year` param matching Letterboxd year exactly; zero results for off-by-one year films | Two-step: search with year first, fallback to search without year |
| TMDB `/search/movie` | Take `results[0]` without year validation | Validate `abs(result_year - lb_year) <= 1` before accepting first result |
| TMDB rate limit | Assume "40 req/s" from PROJECT.md is safe; hammer API with no throttle | Use `asyncio.sleep(0.1)` between calls or semaphore to cap concurrency; TMDB free tier is ~40 requests per 10 seconds |
| Letterboxd zip | Call `zipfile.extractall()` to unpack | Read named entries directly: `z.read("watched.csv")` — never extract to filesystem |
| Letterboxd zip | Expect all CSVs to always be present | Check `z.namelist()` before reading; gracefully handle missing optional files |
| SQLAlchemy + TMDB in same loop | Let TMDB exception poison session | Always `db.rollback()` in except block before continuing to next movie |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Sequential TMDB fetch per movie with no concurrency | 1000-movie import takes 15+ minutes | Use `asyncio.gather` with a semaphore (limit 5-10 concurrent calls) | Imports > ~200 movies; PROJECT.md scopes to sync for now so accept this limit explicitly |
| `db.commit()` inside per-movie loop | Commit latency multiplied by movie count | `db.flush()` per row, single `db.commit()` at end | Any import > ~50 movies becomes noticeably slow |
| `get_movie_details()` fetches trailer video separately (2 TMDB calls per movie) | Import makes 3 TMDB calls per movie (search + details + video) | Skip trailer fetch during import; trailers can be fetched lazily on first view | Imports > 100 movies; 300 TMDB calls vs 100 |
| No in-flight TMDB result cache | Same popular film in multiple CSVs triggers multiple TMDB searches | Build a `resolved: dict[str, int]` cache keyed by Letterboxd URI before hitting TMDB | Any import where same movie appears in watched + ratings + reviews |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Using `zipfile.extractall()` or writing extracted files to disk | Path traversal: a crafted zip can write files anywhere on the server filesystem | Read CSV content directly from zip in memory: `z.read("watched.csv")`; never call `extractall()` |
| No file size validation on upload | A 500MB zip can exhaust memory reading CSVs into strings | Validate `Content-Length` or zip size before processing; set max upload size in FastAPI |
| No zip bomb protection | Compressed zip that expands to gigabytes | Check sum of `file.file_size` across zip entries before reading |
| Passing Letterboxd URI to TMDB as-is | Not a security issue but causes silent failures; just wrong | Only pass `name` and `year` to TMDB search |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Returning 500 on first TMDB failure | User gets no feedback; cannot know what imported and what didn't | Always return summary: `{"imported": N, "skipped": M, "failed": [{"name": ..., "reason": ...}]}` |
| Silently dropping unresolvable films | User wonders why their imported count is lower than expected | Log each failure reason in the response; include film name and why it failed |
| Setting `watched_date` to Letterboxd log date for bulk-imported history | User's entire watch history shows the same date (mass-import artifact) | Use `watched_date` from reviews.csv `Watched Date` field where available; use watched.csv `Date` only as fallback; document this behavior |
| No duplicate detection feedback | Re-importing shows `imported: 0` with no explanation | Return `{"imported": N, "skipped_duplicates": M}` so user knows what was already present |

---

## "Looks Done But Isn't" Checklist

- [ ] **Liked films import:** Verify liked count in response equals total `likes/films.csv` rows, not just liked films that overlap with `watched.csv`
- [ ] **Reviews import:** Verify that movies appearing only in `reviews.csv` (not in `watched.csv`) are still imported — test with `A Minecraft Movie (2025)` equivalent
- [ ] **Year fallback:** Verify that a film with off-by-one year (festival vs. release year) still resolves — manually search TMDB for a known off-by-one case
- [ ] **CRLF handling:** Verify CSV parsing works when zip is read on Linux (CRLF line endings from Letterboxd are standard; confirm `csv.DictReader` on decoded UTF-8 string handles them)
- [ ] **Session recovery:** Verify that if one TMDB call fails mid-import, subsequent movies still import — force a failure and check the result
- [ ] **Duplicate skip:** Verify that re-running import on the same user returns `imported: 0, skipped_duplicates: N` instead of IntegrityError
- [ ] **Tags field:** Confirm whether tags from `reviews.csv` are silently dropped or whether a migration is needed — this is explicitly in PROJECT.md requirements
- [ ] **Watchlist separation:** Verify that watchlist_movies rows are NOT created for films already in watched_movies (a film on the watchlist that was later watched should not appear in both)

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| CSV source independence missed (subset assumption) | MEDIUM | Rewrite merge logic to use URI union; re-run import (idempotent with skip-existing) |
| Wrong TMDB match (popularity bias) | HIGH | No automated recovery; requires per-user data correction or full re-import with corrected resolver |
| Session poisoned mid-import (no per-movie rollback) | LOW | Add try/except with db.rollback(); re-run import (skip-existing prevents duplication) |
| Liked films not imported (update-only approach) | LOW | Run a follow-up pass over likes/films.csv creating missing watched_movies rows |
| Tags silently dropped | LOW-MEDIUM | Add tags JSONB column to watched_movies via migration; re-import to populate |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| CSV subset assumption | Import workflow construction | Integration test: import export where reviewed film is absent from watched.csv |
| URI used for TMDB lookup | Import workflow construction | Unit test: `resolve_tmdb_id("https://boxd.it/abc")` returns None or raises |
| No year fallback | Import workflow construction | Unit test: resolve film with ±1 year discrepancy |
| Popularity bias, wrong film | Import workflow construction | Unit test: `best_match(results, lb_year)` picks correct result from mocked data |
| Session poisoned on exception | Import workflow construction | Integration test: mock TMDB to fail on movie #3; verify movies #1, #2, #4+ all imported |
| N commits in loop | Import workflow construction | Performance test: profile commit count equals 1 for entire batch |
| Liked films need new rows | Import workflow construction + migration | Check import result: liked count == total likes/films.csv rows |
| Zip path traversal | Import workflow construction | Security test: crafted zip with `../` paths; verify no filesystem writes |

---

## Sources

- Direct inspection of `letterboxd-arose3000-2026-03-04-03-09-utc.zip` (actual Letterboxd export, 2026-03-04)
- Cross-referencing watched.csv vs likes/films.csv: 11/16 liked films confirmed absent from watched.csv
- Cross-referencing reviews.csv vs watched.csv: reviewed film confirmed absent from watched.csv
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/tracking/services.py` (per-record commit pattern)
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/movies/services.py` (get_movie_details race condition, 2 TMDB calls per movie)
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/dependencies.py` (no explicit httpx timeout)
- DB schema: `/Users/adamrose/Desktop/blnd/blnd_backend/supabase/migrations/20260302052101_initial_schema.sql` (UniqueConstraint on (user_id, tmdb_id), FK watched_movies → movies)
- PROJECT.md: `/Users/adamrose/Desktop/blnd/.planning/PROJECT.md`

---
*Pitfalls research for: Letterboxd CSV import — FastAPI + SQLAlchemy + TMDB*
*Researched: 2026-03-03*
