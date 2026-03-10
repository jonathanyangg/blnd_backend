# Phase 3: Polish and Hardening - Research

**Researched:** 2026-03-04
**Domain:** TMDB API rate limiting, FastAPI file upload validation, async error isolation, defensive Python
**Confidence:** HIGH

---

## Summary

Phase 3 hardens the Letterboxd import endpoint built in Phase 2 against three specific failure modes: TMDB HTTP 429 rate limit errors on large imports, malicious/oversized file uploads, and cascading failures when individual movies fail during import. The phase adds no new features -- it makes the existing `run_letterboxd_import` workflow safe for production use.

The existing codebase already provides a proven rate-limiting pattern: the seed pipeline in `services.py` uses `asyncio.sleep(0.025)` (~40 req/s) between TMDB calls. The import workflow should adopt the same approach. For file validation, Python stdlib provides `zipfile.is_zipfile()` and `zipfile.BadZipFile` for format validation, and FastAPI's `Header` dependency enables Content-Length checking before the request body is read. The per-movie error isolation already exists (try/except in the loop) but needs a `db.rollback()` guard to prevent dirty session state from poisoning subsequent iterations.

**Primary recommendation:** Add three layers of defense to `workflows.py` and `views.py`: (1) an `asyncio.sleep` delay between TMDB API calls matching the seed pipeline pattern, (2) pre-processing file validation (size limit via Content-Length header, zip format validation via `zipfile.is_zipfile`, decompression ratio check), and (3) a `db.rollback()` call in the per-movie exception handler to reset session state after DB errors.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncio` | stdlib | `asyncio.sleep()` for rate-limit delay between TMDB calls | Already used in seed pipeline (`services.py` line 98); no external dependency |
| `zipfile` | stdlib | `is_zipfile()` for format validation, `BadZipFile` for error handling | Already used in `workflows.py` for extraction; validation is a stdlib method on the same module |
| `fastapi.Header` | FastAPI (current) | Content-Length dependency for pre-read size validation | Already available; used in FastAPI's own documentation for upload size limiting |
| `fastapi.HTTPException` | FastAPI (current) | Return 413/400 errors for rejected uploads | Already imported in `views.py` dependency chain |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `io.BytesIO` | stdlib | Wrap bytes for `is_zipfile()` check | Already used in `_parse_csvs` |
| `logging` | stdlib | Log rate-limit sleeps, validation rejections | Already used throughout `workflows.py` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `asyncio.sleep(0.025)` fixed delay | `aiolimiter` or `asynciolimiter` (token bucket) | External dependency for a sequential loop that doesn't need sophisticated rate limiting. Fixed delay matches the existing seed pipeline pattern and is simpler. |
| Content-Length header check | Chunked reading with size accumulator | More robust against spoofed headers, but Letterboxd exports are small (<5MB) and this adds complexity. Content-Length check is sufficient for the threat model. |
| `zipfile.is_zipfile()` | `python-magic` (libmagic binding) | Heavyweight dependency for something the stdlib already does. `is_zipfile` checks the ZIP magic number. |

**Installation:** No new dependencies needed. All required libraries are already available (stdlib + existing FastAPI).

---

## Architecture Patterns

### Changes to Existing Files

```
app/import_data/
    views.py              # MODIFY: add file validation before calling workflow
    workflows.py          # MODIFY: add rate-limit delay + db.rollback() in error handler
```

No new files are created. This phase modifies two existing files.

### Pattern 1: TMDB Rate-Limit Delay (Matching Seed Pipeline)

**What:** Add `asyncio.sleep()` after each TMDB API call to stay under the ~50 req/s CDN limit.
**When to use:** Any loop that makes sequential TMDB API calls.

```python
# Source: existing pattern in app/import_data/services.py line 16 + 98
TMDB_RATE_LIMIT_DELAY = 0.025  # ~40 req/s — matches seed pipeline

for _uri, record in merged.items():
    try:
        tmdb_id = await _resolve_tmdb_id(record.name, record.year, tmdb_client)
        await asyncio.sleep(TMDB_RATE_LIMIT_DELAY)

        if tmdb_id is None:
            # ... handle failure
            continue

        await get_movie_details(tmdb_id, db, tmdb_client)
        await asyncio.sleep(TMDB_RATE_LIMIT_DELAY)

        # ... DB writes (no TMDB calls, no sleep needed)
    except Exception:
        # ... error handling
```

**Key insight:** Each movie makes up to 2 TMDB calls: one search (`_resolve_tmdb_id`) and one detail fetch (`get_movie_details` -- only if movie is not cached). The delay should be placed after each TMDB call, not just once per loop iteration. For a 100-film import with all movies uncached, this means ~200 calls at ~40/s = ~5 seconds of sleep overhead. Acceptable.

**Why not a semaphore or token bucket:** The loop is already sequential (`for` loop with `await`). There is no concurrency to limit. A fixed sleep after each TMDB call is the simplest correct solution and matches what the seed pipeline already does.

### Pattern 2: Pre-Processing File Validation in views.py

**What:** Validate the uploaded file before passing it to the workflow. Reject bad input with clear HTTP error responses.
**When to use:** At the endpoint level, before `await file.read()` or as early as possible after reading bytes.

```python
# Source: FastAPI docs (https://github.com/fastapi/fastapi/discussions/8167)
import io
import zipfile
from fastapi import Header, HTTPException

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB — generous for Letterboxd exports (<5MB typical)

@router.post("/letterboxd", response_model=ImportSummaryResponse)
async def import_letterboxd(
    file: UploadFile = File(...),
    content_length: int = Header(..., le=MAX_UPLOAD_SIZE),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    # 1. Read bytes (already bounded by Content-Length check above)
    file_bytes = await file.read()

    # 2. Enforce actual size (Content-Length can be spoofed)
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    # 3. Validate zip format
    if not zipfile.is_zipfile(io.BytesIO(file_bytes)):
        raise HTTPException(status_code=400, detail="File is not a valid zip archive")

    result = await workflows.run_letterboxd_import(user_id, file_bytes, db, tmdb_client)
    return result
```

**Content-Length header approach:** The `Header(..., le=MAX_UPLOAD_SIZE)` dependency causes FastAPI to return 422 if the Content-Length header exceeds the limit or is missing. This rejects oversized uploads before the body is fully transmitted. The follow-up `len(file_bytes)` check catches spoofed headers.

### Pattern 3: Zip Bomb Detection via Decompression Ratio

**What:** After confirming the file is a valid zip, check the ratio of total uncompressed size to compressed size. A ratio above a threshold (e.g., 100:1) indicates a zip bomb.
**When to use:** Before extracting any zip entries.

```python
# Source: AWS CodeGuru detector (https://docs.aws.amazon.com/codeguru/detector-library/python/zip-bomb-attack/)
MAX_DECOMPRESSION_RATIO = 100  # 100:1 — extremely generous; real exports are ~2:1

def _validate_zip(file_bytes: bytes) -> None:
    """Validate zip file: format, decompression ratio, expected CSV entries."""
    buf = io.BytesIO(file_bytes)
    if not zipfile.is_zipfile(buf):
        raise ValueError("File is not a valid zip archive")

    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        compressed_size = len(file_bytes)
        total_uncompressed = sum(info.file_size for info in zf.infolist())
        if compressed_size > 0 and total_uncompressed / compressed_size > MAX_DECOMPRESSION_RATIO:
            raise ValueError("Zip decompression ratio too high (possible zip bomb)")
```

### Pattern 4: DB Session Rollback on Per-Movie Errors

**What:** Call `db.rollback()` when a per-movie exception occurs to reset the SQLAlchemy session to a clean state.
**When to use:** Any try/except that catches DB-related exceptions where subsequent iterations need a healthy session.

```python
# Source: SQLAlchemy session management best practices
except Exception:
    db.rollback()  # Reset session state after potential DB error
    logger.warning(
        "Failed to import %s (%s)", record.name, record.year, exc_info=True
    )
    failed_titles.append(record.name)
    failed += 1
    continue
```

**Why this matters:** If a `db.commit()` fails (e.g., a constraint violation that wasn't caught by query-first), the SQLAlchemy session enters a "dirty" state. Without `db.rollback()`, the next `db.add()` or `db.commit()` in a subsequent loop iteration may raise `sqlalchemy.exc.InvalidRequestError` or re-attempt the failed operation, causing a cascade of failures. The `db.rollback()` call is a no-op if the session is clean, so it is always safe.

### Anti-Patterns to Avoid

- **Adding concurrency (asyncio.gather/TaskGroup) to TMDB calls:** The loop is sequential by design. Parallelizing TMDB calls would require concurrent session management (SQLAlchemy sessions are not thread-safe) and would dramatically increase rate-limit risk. Keep it sequential.
- **Checking file.content_type for zip validation:** The `content_type` header is set by the client and can be trivially spoofed. Use `zipfile.is_zipfile()` on the actual bytes instead. Content-type can be logged for debugging but should not be trusted for security.
- **Catching specific exception types in the per-movie handler:** The broad `except Exception` is intentional per IMPT-05. Narrowing to specific exceptions risks missing unexpected error types (e.g., httpx.TimeoutError, KeyError from malformed TMDB response) and aborting the import.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rate limiting | Custom token bucket or semaphore-based limiter | `asyncio.sleep(TMDB_RATE_LIMIT_DELAY)` after each TMDB call | Sequential loop needs only a fixed delay; matches existing seed pipeline pattern |
| Zip format validation | Manual magic-number byte check | `zipfile.is_zipfile(io.BytesIO(file_bytes))` | Stdlib function checks the ZIP magic number correctly |
| Upload size limiting | Custom middleware or streaming size counter | `content_length: int = Header(..., le=MAX)` + `len(file_bytes)` post-read check | FastAPI dependency handles 422 response automatically; post-read check catches spoofed headers |
| Zip bomb detection | Custom decompression monitoring | Check `ZipInfo.file_size` sum vs compressed size ratio | No need to actually decompress; metadata inspection is sufficient |
| DB session recovery | Custom session pool reset logic | `db.rollback()` in exception handler | SQLAlchemy's built-in rollback resets session to clean state |

**Key insight:** Every hardening measure in this phase uses stdlib or existing framework capabilities. No new dependencies are needed.

---

## Common Pitfalls

### Pitfall 1: Sleep Placement After Cached get_movie_details
**What goes wrong:** `get_movie_details` returns immediately from DB cache if the movie is already stored. Adding sleep after it wastes time on no-ops.
**Why it happens:** The function abstracts away whether it made a TMDB call or returned cached data.
**How to avoid:** Accept the overhead. The sleep is 25ms, which is negligible. Alternatively, check if the movie was already cached before calling `get_movie_details` and skip the sleep, but this adds complexity for minimal gain. The seed pipeline does not make this optimization either.
**Warning signs:** Import takes noticeably longer on re-imports where all movies are already cached. Not a real problem -- a 100-film re-import adds only ~2.5 seconds of unnecessary sleep.

### Pitfall 2: Content-Length Header Missing
**What goes wrong:** Some HTTP clients or proxies may not send Content-Length. Using `Header(...)` (required) means these requests get a 422 error.
**Why it happens:** Chunked transfer encoding omits Content-Length.
**How to avoid:** Use `Header(default=0, le=MAX_UPLOAD_SIZE)` to make it optional, then rely on the post-read `len(file_bytes)` check as the real enforcement. Or keep it required -- Letterboxd zip uploads from any standard client (curl, fetch, Postman) will include Content-Length.
**Warning signs:** 422 errors from legitimate clients that use chunked encoding. Monitor and relax if needed.

### Pitfall 3: SQLAlchemy Session State After Failed Commit
**What goes wrong:** A `db.commit()` that fails (e.g., IntegrityError from a race condition) leaves the session in a state where subsequent operations fail with `InvalidRequestError: This Session's transaction has been rolled back due to a previous exception`.
**Why it happens:** SQLAlchemy sessions track transaction state. A failed commit marks the transaction as "rolled back" but does not actually roll back until `db.rollback()` is called.
**How to avoid:** Always call `db.rollback()` in the exception handler. This is safe even if the exception was not DB-related (rollback on a clean session is a no-op).
**Warning signs:** After one movie fails with a DB error, ALL subsequent movies in the same import also fail. The error message mentions "previous exception" or "rolled back".

### Pitfall 4: Zip Bomb via Nested Zips
**What goes wrong:** A malicious zip contains another zip inside, which itself is a zip bomb. The decompression ratio check on the outer zip looks fine.
**Why it happens:** Nested zip bombs bypass single-level decompression ratio checks.
**How to avoid:** The current code only opens specific named CSV files (`watched.csv`, etc.) from the zip, never recursively extracts nested zips. This is inherently safe -- `zf.open('watched.csv')` on a nested zip just returns the raw zip bytes, not the decompressed inner content. No additional protection needed.

### Pitfall 5: Validation Errors Leaking Internal Details
**What goes wrong:** Raising HTTPException with the raw exception message (e.g., `str(e)` from zipfile) may leak file paths or internal state.
**Why it happens:** Python exception messages include implementation details.
**How to avoid:** Use fixed, generic error messages: "File is not a valid zip archive", "File too large", "Zip archive failed validation". Log the actual exception details at WARNING level for debugging.

---

## Code Examples

Verified patterns from the existing codebase and stdlib:

### Rate-Limit Delay (Existing Seed Pipeline Pattern)
```python
# Source: app/import_data/services.py lines 16 + 98
TMDB_RATE_LIMIT_DELAY = 0.025  # ~40 req/s

# In the fetch loop:
await asyncio.sleep(TMDB_RATE_LIMIT_DELAY)
```

### zipfile.is_zipfile Validation
```python
# Source: Python stdlib zipfile module
import io
import zipfile

buf = io.BytesIO(file_bytes)
if not zipfile.is_zipfile(buf):
    raise HTTPException(status_code=400, detail="File is not a valid zip archive")
```

### FastAPI Content-Length Header Dependency
```python
# Source: FastAPI GitHub discussion #8167
from fastapi import Header

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

async def import_letterboxd(
    file: UploadFile = File(...),
    content_length: int = Header(default=0, le=MAX_UPLOAD_SIZE),
    # ...
):
    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
```

### SQLAlchemy Session Rollback in Error Handler
```python
# Source: SQLAlchemy session management docs
except Exception:
    db.rollback()  # Always safe -- no-op if session is clean
    logger.warning("Failed to import %s (%s)", record.name, record.year, exc_info=True)
    failed_titles.append(record.name)
    failed += 1
    continue
```

### Decompression Ratio Check
```python
# Source: AWS CodeGuru zip-bomb detector pattern
MAX_DECOMPRESSION_RATIO = 100

with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
    total_uncompressed = sum(info.file_size for info in zf.infolist())
    compressed_size = len(file_bytes)
    if compressed_size > 0 and total_uncompressed / compressed_size > MAX_DECOMPRESSION_RATIO:
        raise HTTPException(status_code=400, detail="Zip archive failed validation")
```

---

## TMDB Rate Limit Analysis

### Current Import Workflow Call Pattern

For each movie in the import:
1. `_resolve_tmdb_id()` -- 1 TMDB `/search/movie` call (always)
2. `get_movie_details()` -- 0 or 1 TMDB `/movie/{id}` call (0 if cached, 1 if new)

**Worst case (all movies uncached):** 2 TMDB calls per movie.
**Best case (all movies cached):** 1 TMDB call per movie (search only).

### Rate Limit Math

| Scenario | Movies | TMDB Calls | Without Delay | With 25ms Delay |
|----------|--------|------------|---------------|-----------------|
| Small import (uncached) | 40 | 80 | ~2-4 sec (latency-bound) | ~4-6 sec |
| Medium import (uncached) | 100 | 200 | ~5-10 sec | ~10-15 sec |
| Large import (uncached) | 500 | 1000 | ~25-50 sec | ~50-75 sec |
| Re-import (all cached) | 100 | 100 | ~2-5 sec | ~5-8 sec |

Without delay, the sequential loop with network latency (~50-100ms per call) naturally stays around 10-20 req/s. This is under the ~50 req/s limit for most cases, but can spike higher when `get_movie_details` returns from cache (skipping the TMDB call entirely, leaving only the fast search call with minimal DB overhead).

**Conclusion:** The 25ms delay is a safety margin. It prevents bursts when many movies are already cached and the search calls fire rapidly. The overhead is minimal (~2.5 seconds per 100 movies).

### TMDB Rate Limit Official Facts

| Property | Value | Source |
|----------|-------|--------|
| Rate limit | ~50 req/s per IP | TMDB official docs |
| Rate limit response | HTTP 429 | TMDB official docs |
| Daily limit | None | TMDB official docs |
| Rate limit scope | Per IP address (not per API key) | TMDB official docs |

Source: https://developer.themoviedb.org/docs/rate-limiting

---

## Validation Strategy Summary

### Layer 1: Pre-Read (in views.py endpoint signature)
- Content-Length header check via `Header(default=0, le=MAX_UPLOAD_SIZE)`
- Rejects requests with oversized Content-Length before body is read
- Returns 422 automatically via FastAPI validation

### Layer 2: Post-Read, Pre-Processing (in views.py after file.read())
- Actual byte length check: `len(file_bytes) > MAX_UPLOAD_SIZE`
- Zip format validation: `zipfile.is_zipfile(io.BytesIO(file_bytes))`
- Decompression ratio check: sum of uncompressed sizes vs compressed size
- Returns 413 (too large) or 400 (bad format) with clear error messages

### Layer 3: During Processing (in workflows.py)
- Rate-limit delay between TMDB calls: `asyncio.sleep(0.025)`
- Per-movie error isolation: existing try/except with added `db.rollback()`
- These are already partially implemented (try/except) and need enhancement (sleep + rollback)

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| No file size limit | Content-Length header + post-read byte check | Two-layer defense; header rejects early, byte check catches spoofing |
| `await file.read()` on anything | Validate zip format before processing | `is_zipfile()` catches non-zip uploads before CSV parsing attempt |
| No TMDB rate limiting in import | `asyncio.sleep(0.025)` per call | Matches seed pipeline; prevents 429 on large imports |
| try/except without rollback | try/except with `db.rollback()` | Prevents dirty session state from cascading failures |

---

## Open Questions

1. **Content-Length header: required vs optional**
   - What we know: Standard HTTP clients (curl, fetch, Postman) always send Content-Length for file uploads. Chunked transfer encoding omits it.
   - What's unclear: Whether any realistic Letterboxd upload client would omit Content-Length.
   - Recommendation: Use `Header(default=0, le=MAX_UPLOAD_SIZE)` -- optional with default 0. The post-read `len(file_bytes)` check is the real enforcement. This avoids 422 errors from edge-case clients while still rejecting clearly oversized requests early.

2. **MAX_UPLOAD_SIZE value**
   - What we know: Real Letterboxd exports are <1MB (the test export was <1MB with 46+ movies). Even a 5000-film account would produce a zip well under 5MB.
   - What's unclear: Whether there's a theoretical upper bound from Letterboxd.
   - Recommendation: 10MB. This is 10x the largest realistic export and well within server memory limits. Generous enough to never reject legitimate uploads.

3. **Whether to add retry logic for TMDB 429 responses**
   - What we know: The 25ms delay should prevent 429s. The seed pipeline does not retry on 429 either.
   - What's unclear: Whether TMDB 429s include a Retry-After header that could be honored.
   - Recommendation: Do not add retry logic. The fixed delay prevents 429s proactively. If a 429 does occur, it will be caught by the per-movie exception handler and the movie will be added to `failed_titles`. This matches the existing error isolation requirement (IMPT-05). Retry logic is deferred to v2 (TMDB-05 requirement).

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection -- `app/import_data/workflows.py` (current import implementation), `app/import_data/services.py` (seed pipeline with rate limiting pattern), `app/import_data/views.py` (current endpoint)
- Python stdlib documentation -- `zipfile.is_zipfile()`, `zipfile.ZipFile.infolist()`, `zipfile.BadZipFile`
- TMDB official rate limiting docs -- https://developer.themoviedb.org/docs/rate-limiting

### Secondary (MEDIUM confidence)
- FastAPI file upload size limiting -- https://github.com/fastapi/fastapi/discussions/8167 -- Content-Length header dependency pattern
- AWS CodeGuru zip bomb detection pattern -- https://docs.aws.amazon.com/codeguru/detector-library/python/zip-bomb-attack/

### Tertiary (LOW confidence)
- None -- all claims are grounded in codebase inspection, official documentation, or verified community sources.

---

## Metadata

**Confidence breakdown:**
- Rate limiting: HIGH -- existing seed pipeline pattern (`asyncio.sleep(0.025)`) confirmed in codebase; TMDB rate limit (~50 req/s) confirmed from official docs
- File validation: HIGH -- `zipfile.is_zipfile` and `Header` dependency are stdlib/framework features with clear documentation
- Error isolation: HIGH -- `db.rollback()` is standard SQLAlchemy session management; the dirty-session cascade is a well-documented SQLAlchemy behavior
- Pitfalls: HIGH -- derived from direct code inspection of the existing implementation

**Research date:** 2026-03-04
**Valid until:** 2026-04-04 (stable stack, stdlib-heavy -- low churn risk)
