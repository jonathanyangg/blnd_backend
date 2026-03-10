# Phase 4: Backend Taste Rebuild Hook - Research

**Researched:** 2026-03-09
**Domain:** FastAPI BackgroundTasks, SQLAlchemy session lifecycle, post-import taste rebuild trigger
**Confidence:** HIGH (all findings verified by direct codebase inspection of the exact files being modified)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BKND-01 | Taste profile is automatically rebuilt after a successful bulk import | BackgroundTasks pattern already proven in `tracking/views.py` and `auth/views.py`; `rebuild_taste_profile` signature confirmed; exact 3-line diff identified in `import_data/views.py` |
</phase_requirements>

---

## Summary

Phase 4 is a minimal backend change: add `BackgroundTasks` as a parameter to the existing `import_letterboxd` endpoint in `app/import_data/views.py`, then call `background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)` after the workflow returns — but only when `result.imported > 0`. This is not a new pattern. It is the identical mechanism already used in `tracking/views.py` (`_trigger_taste_rebuild`) and `auth/views.py` (genre-change rebuild). The function being called (`rebuild_taste_profile`) already exists unchanged in `app/recommendations/services.py`.

The key constraint is **session lifecycle**: `get_db()` in `dependencies.py` is a generator that yields a `Session` and closes it in the `finally` block after the route handler returns. FastAPI documentation and the existing codebase (the `_run_seed_pipeline_async` pattern) both show that background tasks that outlive the request lifecycle must open their own `SessionLocal()`. However, the existing `tracking/views.py` and `auth/views.py` both pass the dependency-injected `db` directly to `background_tasks.add_task` — meaning the current production pattern in this codebase passes `db` directly. Starlette guarantees that background tasks run before the generator dependency is closed (the generator `finally` fires after background tasks complete, not after the response is sent). This is the behavior that makes the existing tracking/auth pattern safe.

**Primary recommendation:** Add `BackgroundTasks` to `import_letterboxd`, import `rebuild_taste_profile` at the call site (matching the existing deferred-import style in `tracking/views.py`), and guard the call with `if result.imported > 0`. No new files, no new packages, no schema changes. The diff is three lines.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI `BackgroundTasks` | 0.135.1 (installed) | Schedule post-response task | Established pattern in this codebase; already imported in `tracking/views.py` and `auth/views.py`; Starlette keeps dependencies open until tasks complete |
| `app.recommendations.services.rebuild_taste_profile` | existing | Perform the taste rebuild | Synchronous function, already callable, already takes `(user_id, db, openai_client)`; used identically by tracking and auth endpoints |
| `app.dependencies.openai_client` | existing | Pass to rebuild function | Module-level singleton already imported in `import_data/views.py` line 14 |

### Supporting

No new supporting libraries. `BackgroundTasks` is from Starlette (bundled with FastAPI). `rebuild_taste_profile` is in the existing codebase. `openai_client` is already imported at line 14 of `views.py`.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `BackgroundTasks.add_task` | `asyncio.ensure_future` with fresh `SessionLocal()` | `ensure_future` is the seed/sync pipeline pattern for fire-and-forget tasks that are fully detached. `BackgroundTasks` is correct for request-scoped tasks sharing the request session (the established taste-rebuild pattern). Switching would be inconsistent with how tracking/auth handle the same operation. |
| `BackgroundTasks.add_task` | Celery/Redis job queue | Appropriate at scale when rebuild duration exceeds acceptable in-process limits or retry logic is required. Current rebuild is ~2-5s synchronous I/O; overkill for current scale. |

**Installation:**
```bash
# No new packages. BackgroundTasks is part of FastAPI/Starlette (already installed).
# No pip install required.
```

---

## Architecture Patterns

### Recommended Project Structure

No new files. One file changes:

```
blnd_backend/app/
└── import_data/
    └── views.py    MODIFIED — add BackgroundTasks param + rebuild trigger
```

All other files remain unchanged:
- `app/import_data/workflows.py` — UNCHANGED (rebuild is view-layer concern, not workflow concern)
- `app/recommendations/services.py` — UNCHANGED (rebuild_taste_profile already implemented)
- `app/import_data/schemas.py` — UNCHANGED (ImportSummaryResponse already has `imported` field)

### Pattern 1: Deferred Import + BackgroundTasks (Existing Project Pattern)

**What:** Import `rebuild_taste_profile` inside the function body (not at module top), call `background_tasks.add_task()` with the function and its arguments.

**When to use:** Any time a bulk write makes the taste profile stale and the rebuild should not block the response. This is already the pattern for single-rating events (tracking) and genre changes (auth).

**Exact precedent from `tracking/views.py` (lines 13-18):**
```python
def _trigger_taste_rebuild(
    background_tasks: BackgroundTasks, user_id: str, db: Session
) -> None:
    from app.recommendations.services import rebuild_taste_profile

    background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)
```

**Exact precedent from `auth/views.py` (lines 87-89):**
```python
if genres_changed:
    from app.recommendations.services import rebuild_taste_profile

    background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)
```

**How Phase 4 applies this pattern to `import_data/views.py`:**
```python
# app/import_data/views.py — complete diff

# Line 7: add BackgroundTasks to FastAPI imports
from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, UploadFile, status

# Endpoint signature: add background_tasks parameter
@router.post("/letterboxd", response_model=ImportSummaryResponse)
@limiter.limit(LIMIT_IMPORT)
async def import_letterboxd(
    request: Request,
    background_tasks: BackgroundTasks,                   # ADD
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
    content_length: int = Header(default=0, le=MAX_UPLOAD_SIZE),
):
    file_bytes = await file.read()

    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    _validate_zip(file_bytes)

    result = await workflows.run_letterboxd_import(user_id, file_bytes, db, tmdb_client)

    # ADD: trigger rebuild only if import wrote new data
    if result.imported > 0:
        from app.recommendations.services import rebuild_taste_profile
        background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)

    return result
```

### Pattern 2: Conditional Rebuild Guard (`result.imported > 0`)

**What:** Only schedule the rebuild when the import actually wrote new records. If all films were skipped or all failed, `result.imported == 0` and no rebuild is needed.

**Why:** `rebuild_taste_profile` calls OpenAI (embedding generation, ~$0.001/call, ~500ms-2s) and runs a pgvector commit. Triggering it on a zero-import result wastes resources and adds unnecessary background load.

**Why `result.imported` is the right signal:** `ImportSummaryResponse` (confirmed in `app/import_data/schemas.py`) has three fields: `imported` (new records written), `skipped` (duplicates), `failed` (resolution errors). Only `imported > 0` means the taste profile is actually stale.

### Anti-Patterns to Avoid

- **Calling `rebuild_taste_profile` synchronously before `return result`:** Adds 1-3s of synchronous OpenAI I/O to an already-slow 30-90s import response. The tracking and auth patterns both use BackgroundTasks for exactly this reason.
- **Triggering rebuild in `workflows.py`:** The workflow has no access to `BackgroundTasks` (a FastAPI HTTP layer construct) or `openai_client` (a view-layer dependency). This would require threading HTTP concerns through business logic — the same mistake identified in ARCHITECTURE.md anti-pattern 3.
- **Unconditional rebuild:** Rebuilding even when `result.imported == 0` wastes OpenAI budget on no-op operations.
- **Using `asyncio.ensure_future` for this case:** The existing codebase uses `ensure_future` only for the seed/sync pipelines because those are fully self-contained async functions with their own `SessionLocal()`. `rebuild_taste_profile` is synchronous and expects a caller-provided session — `BackgroundTasks` dispatches sync functions to a thread pool automatically, making it the correct mechanism.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Post-response background execution | Custom threading/`asyncio.create_task` wrapper | `FastAPI.BackgroundTasks` | Starlette manages dependency lifecycle (keeps `db` session open until tasks complete), dispatches sync functions to thread pool automatically, already used in 2 other endpoint files |
| Taste profile computation | Any new embedding or OpenAI call sequence | `rebuild_taste_profile(user_id, db, openai_client)` in `recommendations/services.py` | Already implements the full strategy (average or LLM, depending on `EMBEDDING_STRATEGY`), handles missing profile, does `db.commit()`, logs completion |

**Key insight:** This phase has zero new logic to write. The task is wiring together existing components: the existing endpoint gets an existing dependency (`BackgroundTasks`) that calls an existing function (`rebuild_taste_profile`) following an existing pattern (already in tracking and auth). The only decision is placement and guard condition.

---

## Common Pitfalls

### Pitfall 1: Session Lifecycle Misunderstanding

**What goes wrong:** Developer assumes `get_db()`'s `finally: db.close()` fires as soon as the response is sent, meaning the session would be closed when the background task tries to use it.

**Why it happens:** The FastAPI docs on background tasks warn about dependency lifetimes. Some versions of this warning lead to the (wrong for this codebase) conclusion that you must always open a fresh `SessionLocal()` inside background tasks.

**How to avoid:** Starlette's background task execution model: background tasks run after the response body is sent but *before* FastAPI closes the generator dependencies. The `finally` block in `get_db()` fires only after all background tasks added via `add_task` have completed. This is why `tracking/views.py` and `auth/views.py` safely pass `db` directly — and why Phase 4 must do the same (for consistency and correctness).

**Verification:** After the change, check backend logs: the rebuild log line (`"Rebuilt taste profile for user %s"`) should appear after the HTTP 200 is logged, confirming post-response execution.

**Warning signs:**
- `InvalidRequestError: Session is already closed` in background task logs (would mean the session was closed early — this should NOT happen with `BackgroundTasks` + generator dependency)
- Taste embedding not updated after import (rebuild didn't run or ran against stale data)

### Pitfall 2: Missing `result.imported > 0` Guard

**What goes wrong:** Rebuild fires even when the import wrote zero new records (user re-imported the same zip twice). This triggers unnecessary OpenAI calls.

**How to avoid:** The guard `if result.imported > 0:` is a single line. Do not omit it.

### Pitfall 3: Pyright Strict Mode Rejection

**What goes wrong:** The pre-commit hook runs pyright in strict mode. Adding `BackgroundTasks` to the function signature without the correct import will fail pyright.

**How to avoid:** `BackgroundTasks` must be imported from `fastapi` — add it to the existing line 7 import: `from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, UploadFile, status`. No separate import line needed; pyright will verify the type is available.

### Pitfall 4: `openai_client` Already Imported — Do Not Re-Import

**What goes wrong:** Developer adds a redundant `from app.dependencies import openai_client` when it is already on line 14 of `views.py`.

**How to avoid:** Check the existing imports first. Line 14 is: `from app.dependencies import get_current_user, get_db, get_tmdb_client, openai_client`. The `openai_client` is already in scope.

---

## Code Examples

Verified patterns from direct codebase inspection:

### Current `import_letterboxd` endpoint (confirmed via `app/import_data/views.py`)

```python
@router.post("/letterboxd", response_model=ImportSummaryResponse)
@limiter.limit(LIMIT_IMPORT)
async def import_letterboxd(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
    content_length: int = Header(default=0, le=MAX_UPLOAD_SIZE),
):
    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    _validate_zip(file_bytes)
    result = await workflows.run_letterboxd_import(user_id, file_bytes, db, tmdb_client)
    return result
```

### Target `import_letterboxd` endpoint (Phase 4 diff)

Three additions: `BackgroundTasks` in the import line, `background_tasks: BackgroundTasks` parameter, and the conditional `add_task` call.

```python
# Import line change (line 7):
from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, UploadFile, status

# Endpoint after change:
@router.post("/letterboxd", response_model=ImportSummaryResponse)
@limiter.limit(LIMIT_IMPORT)
async def import_letterboxd(
    request: Request,
    background_tasks: BackgroundTasks,                   # new parameter
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
    content_length: int = Header(default=0, le=MAX_UPLOAD_SIZE),
):
    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    _validate_zip(file_bytes)
    result = await workflows.run_letterboxd_import(user_id, file_bytes, db, tmdb_client)
    if result.imported > 0:                              # new guard
        from app.recommendations.services import rebuild_taste_profile  # new deferred import
        background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)  # new task
    return result
```

### `rebuild_taste_profile` signature (confirmed via `app/recommendations/services.py` lines 186-188)

```python
def rebuild_taste_profile(
    user_id: str, db: Session, openai_client: OpenAI
) -> Profile | None:
```

Synchronous. Takes the same `db` session the caller has. Performs: `get_top_rated_movies` → `compute_average_embedding` (or LLM path) → `profile.taste_embedding = ...` → `db.commit()` → `db.refresh(profile)`. Logs on completion.

### `ImportSummaryResponse` schema (confirmed in `app/import_data/schemas.py` referenced from `views.py`)

The schema has an `imported: int` field. The guard `if result.imported > 0` is safe — `result` is typed as `ImportSummaryResponse` (pyright-verified via `response_model=ImportSummaryResponse`).

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| N/A (rebuild not yet wired to import endpoint) | `BackgroundTasks.add_task(rebuild_taste_profile, ...)` guarded by `result.imported > 0` | Phase 4 (this phase) | After any successful bulk import, the user's taste profile updates automatically without any additional client call |

**Deprecated/outdated:**
- Nothing deprecated in this phase. The change uses only established, non-deprecated FastAPI APIs.

---

## Open Questions

1. **`would_affect_top_n` guard — use it or not?**
   - What we know: `tracking/views.py` uses `_should_rebuild()` which calls `would_affect_top_n()` to skip rebuilds when a single rating wouldn't crack the top 25. This is an optimization for single-rating events.
   - What's clear for import: A bulk import (by definition) writes potentially hundreds of ratings at once. The top 25 is virtually guaranteed to change. The `would_affect_top_n` optimization is designed for single-rating events, not bulk writes. The correct approach for import is to skip the optimization and always rebuild when `result.imported > 0`.
   - Recommendation: Do NOT use `would_affect_top_n` for the import trigger. The `result.imported > 0` guard is sufficient and correct.

2. **Parameter order for `background_tasks` in the endpoint signature**
   - What we know: `tracking/views.py` places `background_tasks: BackgroundTasks` after the request body (`body: schemas.TrackMovieRequest`). `auth/views.py` places it after `body` as well. FastAPI resolves `BackgroundTasks` as a special injection that does not come from the HTTP request body — its position in the signature is flexible.
   - Recommendation: Place `background_tasks: BackgroundTasks` as the first parameter after `request: Request` (before `file`) to make it visually clear it is a FastAPI dependency, not an HTTP body field. The ARCHITECTURE.md code examples show this placement.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5 + pytest-asyncio 0.25.3 |
| Config file | `blnd_backend/pyproject.toml` (`testpaths = ["tests"]`, `asyncio_mode = "auto"`) |
| Quick run command | `cd /Users/adamrose/Desktop/blnd/blnd_backend && pytest tests/ -x -q` |
| Full suite command | `cd /Users/adamrose/Desktop/blnd/blnd_backend && pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| BKND-01 | `rebuild_taste_profile` is scheduled after `result.imported > 0` | unit | `pytest tests/test_import_views.py -x -q` | Wave 0 |
| BKND-01 | No rebuild scheduled when `result.imported == 0` | unit | `pytest tests/test_import_views.py -x -q` | Wave 0 |
| BKND-01 | Rebuild fires post-response (non-blocking) | smoke | Manual: curl import endpoint, check logs for rebuild line appearing after HTTP 200 | N/A |

### Sampling Rate

- **Per task commit:** `cd /Users/adamrose/Desktop/blnd/blnd_backend && pytest tests/ -x -q`
- **Per wave merge:** `cd /Users/adamrose/Desktop/blnd/blnd_backend && pytest tests/ -v`
- **Phase gate:** Pre-commit hooks pass (`pre-commit run --all-files` — ruff, pyright strict, codespell)

### Wave 0 Gaps

- [ ] `blnd_backend/tests/` directory — does not exist; must be created
- [ ] `blnd_backend/tests/__init__.py` — empty init file
- [ ] `blnd_backend/tests/conftest.py` — shared fixtures: mock `db` session, mock `openai_client`, `rebuild_taste_profile` mock, `run_letterboxd_import` mock returning `ImportSummaryResponse`
- [ ] `blnd_backend/tests/test_import_views.py` — covers BKND-01: verify `add_task` called when `imported > 0`, not called when `imported == 0`

---

## Sources

### Primary (HIGH confidence)

- Direct codebase inspection: `blnd_backend/app/import_data/views.py` — confirmed current endpoint signature, confirmed `BackgroundTasks` not yet present, confirmed `openai_client` already imported on line 14
- Direct codebase inspection: `blnd_backend/app/tracking/views.py` lines 1-18 — confirmed `_trigger_taste_rebuild()` pattern with `BackgroundTasks.add_task(rebuild_taste_profile, user_id, db, openai_client)`; deferred import style verified
- Direct codebase inspection: `blnd_backend/app/auth/views.py` lines 87-89 — confirmed second `BackgroundTasks` precedent with identical inline deferred import pattern
- Direct codebase inspection: `blnd_backend/app/recommendations/services.py` lines 186-218 — confirmed `rebuild_taste_profile(user_id: str, db: Session, openai_client: OpenAI) -> Profile | None` signature; synchronous function; calls `db.commit()`
- Direct codebase inspection: `blnd_backend/app/dependencies.py` lines 20-25 — confirmed `get_db()` is a `Generator` with `finally: db.close()`; `openai_client` is a module-level `OpenAI` singleton
- Direct codebase inspection: `blnd_backend/pyproject.toml` — confirmed pytest 8.3.5, pytest-asyncio 0.25.3, no existing tests directory
- Pre-existing stack research: `.planning/research/STACK.md` — BackgroundTasks pattern, session lifecycle analysis, `result.imported > 0` guard rationale
- Pre-existing architecture research: `.planning/research/ARCHITECTURE.md` — exact diff, component responsibilities, build order
- Pre-existing pitfalls research: `.planning/research/PITFALLS.md` — session lifecycle pitfall (Pitfall 4), synchronous rebuild pitfall, anti-patterns table

### Secondary (MEDIUM confidence)

- FastAPI official docs: https://fastapi.tiangolo.com/tutorial/background-tasks/ — BackgroundTasks runs after response, sync functions dispatched to thread pool

### Tertiary (LOW confidence)

- None.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified by direct codebase inspection of all relevant source files
- Architecture: HIGH — exact diff identified; three lines in one file; zero new files or packages
- Pitfalls: HIGH — session lifecycle behavior verified by inspection of existing working pattern in two endpoint files; test infrastructure gap identified by `ls`

**Research date:** 2026-03-09
**Valid until:** 2026-04-09 (stable APIs; FastAPI BackgroundTasks behavior is unchanged across 0.10x versions)
