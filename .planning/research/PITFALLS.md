# Pitfalls Research

**Domain:** iOS file picker + long-running multipart upload + backend taste profile rebuild (v1.1 milestone)
**Researched:** 2026-03-09
**Confidence:** HIGH (findings derived from direct inspection of existing codebase, Apple developer forums, and verified against FastAPI/SQLAlchemy official docs)

---

## Critical Pitfalls

### Pitfall 1: Security-Scoped Resource Released Before Upload Completes

**What goes wrong:**
The file URL returned by `.fileImporter` is a security-scoped URL — it grants temporary sandbox access to a file outside the app container. If `stopAccessingSecurityScopedResource()` is called (or the security scope simply expires) before the upload finishes reading the file data, the upload receives a permission error mid-stream, or reads zero bytes silently. This is particularly dangerous when the read is deferred until an async Task starts, because by then the scope may already have been released.

**Why it happens:**
The `onCompletion` closure of `.fileImporter` provides the URL but does not keep the scope open indefinitely. Developers often store the URL, call `stopAccessingSecurityScopedResource()` in a `defer` block inside the completion handler, then kick off an async upload Task — by the time the Task runs, the scope is already released. Alternatively, scoping issues arise when the URL is passed across async suspension points without holding the scope open.

**How to avoid:**
Read the file data to `Data` synchronously inside the security scope before leaving the completion handler. The Data copy is safe to hold indefinitely once read:
```swift
.fileImporter(isPresented: $showPicker, allowedContentTypes: [.zip]) { result in
    guard let url = try? result.get() else { return }
    guard url.startAccessingSecurityScopedResource() else { return }
    defer { url.stopAccessingSecurityScopedResource() }
    // Read bytes NOW, inside the scope — not in a Task later
    let data = try? Data(contentsOf: url)
    uploadData = data
}
```
Never store the URL and defer the read to a Task. Read bytes inside the completion closure, store the Data.

**Warning signs:**
- Upload sends a non-nil but zero-byte body to the server (zip validation fails with "not a valid zip archive")
- `Data(contentsOf: url)` returns nil or throws a permissions error in a Task context
- Import works in Simulator (less strict sandboxing) but fails on a physical device

**Phase to address:**
iOS import screen phase — the file picker implementation step, before any upload code is written.

---

### Pitfall 2: URLSession Default 60-Second Request Timeout Kills Large Imports

**What goes wrong:**
`URLRequest.timeoutInterval` defaults to 60 seconds. The Letterboxd import for a 2000-film library takes 30-90 seconds on the backend (2 TMDB calls per film at 25ms delay = ~100 seconds at full throttle). The iOS URL loading system silently kills the request with `NSURLErrorTimedOut` (-1001) partway through, while the backend continues processing. The user sees an error; the backend import completes successfully. The iOS app shows a failure and the taste profile is never rebuilt on the client side.

**Why it happens:**
`URLSession.shared` uses `URLSessionConfiguration.default`, which has `timeoutIntervalForRequest = 60`. This is not the total request duration — it is the maximum time allowed between data packets received. For a synchronous endpoint that processes for 90 seconds before sending any response body, the iOS client times out before the first byte arrives.

**How to avoid:**
Create a dedicated `URLSessionConfiguration` with an extended `timeoutIntervalForRequest` for the import endpoint. 300 seconds (5 minutes) is safe for this use case:
```swift
let config = URLSessionConfiguration.default
config.timeoutIntervalForRequest = 300
config.timeoutIntervalForResource = 600
let importSession = URLSession(configuration: config)
```
The existing `APIClient.shared` uses `URLSession.shared` — the import call must NOT go through `APIClient.request()`. It needs its own session configuration.

**Warning signs:**
- Import works for libraries under ~200 films (completes in <60s) but fails for larger libraries
- Error is `NSURLErrorTimedOut` (-1001) not a server-side 4xx/5xx
- Backend logs show import completing successfully after the iOS error fires
- Works in dev against `localhost:8000` (low latency, fast) but fails against production host

**Phase to address:**
iOS upload implementation phase — specifically when wiring the upload to URLSession.

---

### Pitfall 3: APIClient.request() Cannot Send Multipart — It Only Sends JSON

**What goes wrong:**
The existing `APIClient.request()` sets `Content-Type: application/json` unconditionally and encodes the body with `JSONEncoder`. Attempting to upload a zip file through it sends a JSON-encoded base64 blob (if it even compiles), not `multipart/form-data`. FastAPI's `UploadFile = File(...)` dependency expects a multipart body; sending JSON triggers a 422 Unprocessable Entity response.

**Why it happens:**
The natural instinct is to reuse the existing `APIClient` pattern. The existing codebase has no precedent for multipart uploads, so the constraint is invisible until the endpoint returns 422.

**How to avoid:**
Write a standalone upload function (not through `APIClient.request()`) that constructs the multipart body manually and uses a custom URLSession:
```swift
func buildMultipartBody(data: Data, boundary: String) -> Data {
    var body = Data()
    let crlf = "\r\n"
    body.append("--\(boundary)\(crlf)".data(using: .utf8)!)
    body.append("Content-Disposition: form-data; name=\"file\"; filename=\"letterboxd.zip\"\(crlf)".data(using: .utf8)!)
    body.append("Content-Type: application/zip\(crlf)\(crlf)".data(using: .utf8)!)
    body.append(data)
    body.append("\(crlf)--\(boundary)--\(crlf)".data(using: .utf8)!)
    return body
}
```
The `Content-Type` header on the URLRequest must be `multipart/form-data; boundary=<boundary>` — the same boundary string used in the body. A mismatch causes FastAPI to return 422 with no useful error message.

**Warning signs:**
- FastAPI returns 422 `Unprocessable Entity` with body `{"detail": [{"type": "missing", "loc": ["body", "file"]}]}`
- Sending correctly structured multipart from curl works but the iOS request does not
- Backend `file.size` is 0 or `file.content_type` is `application/json` instead of `application/zip`

**Phase to address:**
iOS upload implementation phase — the multipart body construction step.

---

### Pitfall 4: Taste Profile Rebuild Triggered Before the DB Commit Completes

**What goes wrong:**
The taste profile rebuild reads the user's top-rated `watched_movies` entries from the database. If the rebuild is triggered as a `BackgroundTask` inside the same request handler that runs the import, there is a race condition: the import's `db.commit()` may not have finished before the rebuild task reads the database. The rebuild runs against the pre-import data and produces a stale taste profile. The user's newly imported 2000 ratings have no effect.

**Why it happens:**
FastAPI `BackgroundTask` functions added via `background_tasks.add_task()` run after the response is sent, but they share the same process. If the import endpoint's `db.commit()` (at the end of `run_letterboxd_import`) and the rebuild's `db.query()` run in close succession, the rebuild can execute before Postgres propagates the commit to the connection pool. The existing codebase's `run_letterboxd_import` in `workflows.py` does a single `db.commit()` at the end — this must fully complete before the rebuild starts.

**How to avoid:**
Do not pass the dependency-injected `db` session to a `BackgroundTask`. The `get_db()` dependency closes the session at the end of the request's yield. Background tasks execute after the response is sent — the session is already closed. Always open a fresh `SessionLocal()` inside the background task:
```python
async def _rebuild_taste_async(user_id: str) -> None:
    db = SessionLocal()  # fresh session — not the request's session
    try:
        await rebuild_taste_profile(user_id, db, openai_client)
    except Exception:
        logger.exception("Taste rebuild failed for %s", user_id)
    finally:
        db.close()
```
The import endpoint should call `db.commit()` (already done in `run_letterboxd_import`), return the response, then add the rebuild as a background task. The commit happens before the background task starts because FastAPI sends the response only after the path function returns.

**Warning signs:**
- Taste profile unchanged after a large import that should have reshaped it
- Background task logs show rebuild completing but `taste_embedding` on the profile was not updated
- "Recommendations still look the same" after importing 2000 films
- `InvalidRequestError: Session is already closed` in background task logs (session reuse across request boundary)

**Phase to address:**
Backend rebuild trigger phase — the endpoint modification step in `import_data/views.py`.

---

### Pitfall 5: SwiftUI @Observable State Updated From Non-Main-Actor Context

**What goes wrong:**
When the URLSession completion (or a Swift `async` Task) publishes upload progress or result data to an `@Observable` view model, the update may arrive on a background thread. Writing `@Observable` properties from a background thread causes runtime warnings in debug and crashes or visual glitches in production on iOS 17.

**Why it happens:**
The zero-third-party-deps constraint means no Combine `receive(on: RunLoop.main)`. Developers forget to dispatch back to the main actor after an `await` suspension point or after reading URLSession delegate callbacks. The existing `APIClient` uses `async/await` throughout — `await URLSession.shared.data(for:)` resumes on an arbitrary thread, not the main actor.

**How to avoid:**
Mark the upload view model (or the import state object) with `@MainActor`. Any `@Observable` class that drives UI state for upload progress must be `@MainActor`:
```swift
@MainActor
@Observable
final class ImportState {
    var progress: Double = 0
    var isUploading: Bool = false
    var result: ImportResult? = nil
}
```
Alternatively, wrap state-mutating code in `await MainActor.run { ... }` at each update site. The `@MainActor` class annotation is simpler and less error-prone.

**Warning signs:**
- Xcode runtime warning: "Publishing changes from background threads is not allowed"
- Progress bar updates are choppy or delayed, then flush all at once
- App crashes on device but not in Simulator (Simulator thread checking is looser)
- Upload result never appears even though network request succeeded

**Phase to address:**
iOS import screen phase — when designing the import view model.

---

### Pitfall 6: UTType.zip Not Available on All Targets — Causes Compile Error or Silent Rejection

**What goes wrong:**
`UTType.zip` is not a static member on `UTType` in all SDK versions. On iOS 16 and earlier, the correct type is `UTType(filenameExtension: "zip")` or `UTType("public.zip-archive")`. On iOS 17+, `UTType.zip` exists as a convenience. The project targets iOS 17+, so `UTType.zip` should work — but if the UniformTypeIdentifiers import is missing, or if the wrong type string is used, the file picker either shows no files at all or shows all files (content types ignored).

**Why it happens:**
The `UniformTypeIdentifiers` framework is not automatically imported in all file contexts. Forgetting `import UniformTypeIdentifiers` at the top of the view file causes a compile error that surfaces the issue immediately. However, using the wrong UTType string (e.g. `UTType("com.pkware.zip-archive")` vs `UTType("public.zip-archive")`) compiles fine but the picker may show zero files if the type is unrecognized on the device.

**How to avoid:**
Use the static convenience member with an explicit import:
```swift
import UniformTypeIdentifiers

.fileImporter(
    isPresented: $showPicker,
    allowedContentTypes: [UTType.zip],
    allowsMultipleSelection: false
)
```
`UTType.zip` resolves to `public.zip-archive` which covers standard Letterboxd exports. Test on a physical device — the Simulator's Files app behaves differently than a real device for content type filtering.

**Warning signs:**
- File picker shows no files at all (content type rejected by the picker)
- Compile error mentioning `UTType` not found (missing import)
- Picker shows all file types instead of only zip files (wrong or nil UTType)

**Phase to address:**
iOS import screen phase — the file picker declaration step.

---

### Pitfall 7: Long-Running Synchronous SQLAlchemy Import Blocks the FastAPI Event Loop

**What goes wrong:**
`run_letterboxd_import()` is an `async` function but it calls synchronous SQLAlchemy ORM methods (`db.query()`, `db.add()`, `db.commit()`) inside an `async def` endpoint handler. Each SQLAlchemy call blocks the event loop thread for its duration. For a 2000-film import with hundreds of DB reads and writes, the event loop is blocked for the entire import duration. All other concurrent requests to the API (from other users) are queued and stall until the import completes.

**Why it happens:**
The existing backend uses sync SQLAlchemy (not SQLAlchemy async). This is a known, accepted tradeoff throughout the codebase. The import workflow is the first place where this tradeoff becomes severe: a single user's import monopolizes the only async worker thread for 30-90 seconds.

**How to avoid:**
Two acceptable approaches for this codebase:

**Option A (simpler — recommended for v1.1):** Convert the import endpoint to a sync `def` function, which FastAPI automatically runs in a threadpool, freeing the event loop:
```python
@router.post("/letterboxd", response_model=ImportSummaryResponse)
@limiter.limit(LIMIT_IMPORT)
def import_letterboxd(  # sync def, not async def
    ...
```
Note: cannot `await` async functions inside a sync def, so async TMDB calls need wrapping or the endpoint stays `async` with `run_in_threadpool`.

**Option B:** Wrap the SQLAlchemy-heavy import call in `run_in_threadpool` from `fastapi.concurrency`. This keeps the endpoint `async` and offloads blocking work to a thread:
```python
from fastapi.concurrency import run_in_threadpool
result = await run_in_threadpool(
    workflows.run_letterboxd_import_sync, user_id, file_bytes, db, tmdb_client
)
```
The current implementation using `await workflows.run_letterboxd_import(...)` directly blocks the event loop.

**Warning signs:**
- All API endpoints become slow/unresponsive during an active import
- Uvicorn logs show requests queuing up
- Gunicorn worker timeout (if deployed with Gunicorn) kills the import mid-flight with 504
- Health check endpoint (`GET /health`) stops responding during import

**Phase to address:**
Backend rebuild trigger phase — when reviewing the import endpoint for production readiness.

---

### Pitfall 8: Upload Progress Unavailable Through async/await URLSession — Requires Delegate

**What goes wrong:**
`URLSession.shared.data(for: request)` (the async/await API) does not expose upload progress. It returns only when the response arrives. For a 30-90 second import, the iOS UI shows no feedback — the user does not know if the upload is stuck, still running, or complete. This is a UX failure that makes the feature feel broken.

**Why it happens:**
The Swift concurrency URLSession APIs (`data(for:)`, `upload(for:from:)`) are designed for simplicity. Progress tracking requires the delegate-based API (`URLSessionTaskDelegate`). The zero-third-party-deps constraint means no Alamofire progress callbacks.

**How to avoid:**
Use `URLSession.upload(for:from:delegate:)` (iOS 15+) which accepts an inline delegate, or implement `URLSessionTaskDelegate` on the import class and track `urlSession(_:task:didSendBodyData:totalBytesSent:totalBytesExpectedToSend:)`:
```swift
func urlSession(
    _ session: URLSession,
    task: URLSessionTask,
    didSendBodyData bytesSent: Int64,
    totalBytesSent: Int64,
    totalBytesExpectedToSend: Int64
) {
    let progress = Double(totalBytesSent) / Double(totalBytesExpectedToSend)
    Task { @MainActor in
        importState.uploadProgress = progress
    }
}
```
An indeterminate progress indicator (spinner) is acceptable if delegate-based progress is deferred, but the UI must at minimum switch to a "processing on server" state after the upload bytes complete, since the backend takes additional time to run the import after receiving all bytes.

**Warning signs:**
- Progress bar stuck at 0% for the entire import duration
- User force-quits the app thinking it is frozen
- No differentiation between "uploading" and "server processing" states

**Phase to address:**
iOS upload implementation phase — UI state machine design step.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Reuse `APIClient.request()` for the upload | Less new code | 422 error from server; JSON encoding incompatible with multipart | Never — multipart requires its own path |
| Skip URLSession timeout configuration | Simpler code | 60s default kills large imports silently | Never — must set `timeoutIntervalForRequest >= 300` |
| Trigger taste rebuild synchronously inside the import endpoint | Simpler flow | Doubles endpoint duration; blocks event loop even longer | Never — always async via BackgroundTask |
| Pass the request `db` session to a BackgroundTask | Avoids creating new session | Session is closed before task runs; crashes or stale reads | Never — create a fresh SessionLocal() in background tasks |
| Show a spinner with no progress feedback | Faster to ship | Users force-quit; no way to distinguish frozen vs. processing | Acceptable for MVP if "processing on server" state is shown after bytes sent |
| Import endpoint as `async def` with blocking SQLAlchemy | No code changes needed | Blocks event loop for 30-90s; starves all other API consumers | Never in production — use sync def or run_in_threadpool |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| SwiftUI `.fileImporter` | Store the URL and read it in a later Task | Read `Data(contentsOf: url)` immediately inside the `onCompletion` closure while the security scope is open |
| URLSession multipart | Set `Content-Type: application/json` via `APIClient` | Set `Content-Type: multipart/form-data; boundary=<uuid>` on the URLRequest; body boundary must match header boundary exactly |
| FastAPI `UploadFile` | Check `Content-Length` header for size enforcement | Also check `len(file_bytes)` after `.read()` — header can be spoofed; the existing codebase correctly does both |
| FastAPI `BackgroundTasks` | Pass `db = Depends(get_db)` to the background task | Instantiate a fresh `SessionLocal()` inside the task function; the yielded session is closed after the response is sent |
| Taste rebuild timing | Trigger rebuild before `db.commit()` completes | FastAPI sends response only after the path function returns and `db.commit()` runs; `add_task()` fires after response — ordering is guaranteed |
| SQLAlchemy in async endpoint | Call blocking ORM methods in `async def` | Either use sync `def` (FastAPI threads it) or wrap with `run_in_threadpool` |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Synchronous SQLAlchemy inside `async def` import handler | API unresponsive for all users during import | Convert endpoint to `def` or wrap with `run_in_threadpool` | Any import > ~50 films on production with concurrent users |
| Taste rebuild triggered synchronously in import endpoint | Import takes 2x longer; user waits for rebuild too | Always run rebuild as `BackgroundTask` (after response sent) | Immediately for large libraries |
| `URLSession.shared` default 60s request timeout | Large library imports time out on iOS before server responds | Custom `URLSessionConfiguration` with 300s timeout | Libraries > ~200 films (backend takes >60s) |
| Reading file data in async Task after security scope release | Upload sends 0 bytes | Read data synchronously inside `onCompletion` closure | Every time on physical device (Simulator is more permissive) |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Passing request's `db` session to background task | Session state corruption; potential data from wrong transaction context | Always create fresh `SessionLocal()` in background tasks |
| No rate limit on taste rebuild trigger | User could hammer `/import/letterboxd` 3/hour × rebuild cost = sustained CPU spike | Existing `LIMIT_IMPORT = 3/hour` covers the upload endpoint; ensure rebuild is only triggered once per successful import, not on partial failure |
| iOS security-scoped URL stored beyond scope lifetime | File access from outside sandbox, permission escalation | Read file bytes inside security scope; never persist the URL |
| Upload `Content-Length` not validated against actual file size | Server reads arbitrary-length body if header is absent or incorrect | Existing backend checks both `content_length` header AND `len(file_bytes)` — preserve both checks |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No distinction between "uploading" and "server processing" phases | User sees spinner stuck at "uploading" while server runs 60-second import | Two-phase UI: progress bar during upload bytes, then "Importing films..." indefinite indicator during server processing |
| Import result shown before taste rebuild completes | User navigates to recommendations immediately; sees stale results | Either wait for rebuild to confirm complete (adds latency) or show "Updating your taste profile..." notification in the UI that clears after rebuild endpoint confirms |
| File picker shows no content type restriction | User can pick any file; ZIP validation error only surfaces after upload attempt | Set `allowedContentTypes: [UTType.zip]` to restrict picker to zip files; fail early in the client |
| Error from timeout (NSURLErrorTimedOut) shown as generic "Network error" | User retries, causing duplicate import triggers (3/hour limit may hit) | Catch `-1001` specifically and show "Import is taking longer than expected — check back in a few minutes" rather than prompting retry |

---

## "Looks Done But Isn't" Checklist

- [ ] **File picker on device:** Test `UTType.zip` filtering on a real iPhone with Letterboxd zip in Files app — Simulator has more permissive file system access
- [ ] **Security scope:** Verify upload sends correct byte count (not 0) by logging `file_bytes` size on backend before zip validation
- [ ] **Timeout:** Test with a large library (2000+ films) from a production-latency host — localhost hides timeout issues
- [ ] **Multipart boundary:** Verify the boundary in the `Content-Type` header exactly matches the boundary string in the body — a mismatch returns 422 with no useful message
- [ ] **Background task session:** Verify taste rebuild background task creates its own `SessionLocal()` — not the request's `db` — by checking import logs show rebuild running after response was sent
- [ ] **@MainActor:** Verify no "Publishing changes from background threads" warnings in Xcode console during upload
- [ ] **APIClient bypass:** Verify the import upload does NOT go through `APIClient.request()` — confirm `Content-Type: multipart/form-data` in network inspector, not `application/json`
- [ ] **Rate limit behavior:** Trigger import 3 times; confirm 4th returns 429 not a crash; confirm rate limit key is the JWT sub, not IP (so it is per-user not per-device)
- [ ] **Rebuild trigger:** After a large import, navigate to recommendations and confirm `taste_embedding` on the profile row is non-null and updated (check via Supabase dashboard)
- [ ] **Stale taste profile:** Confirm that a user with no prior ratings gets a taste profile after import (first-time rebuild path, not just update path)

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Security scope released before read | LOW | Restructure file picker completion closure; no data loss |
| Timeout on large import | MEDIUM | Backend import may have completed; check `/import/letterboxd` again (skip-existing is idempotent); increase client timeout configuration |
| Multipart body/header boundary mismatch | LOW | Fix boundary string construction; no server-side changes needed |
| Taste rebuild background task used closed session | LOW | Add fresh `SessionLocal()` in background task; manually trigger rebuild via `POST /recommendations/me/refresh` |
| Event loop blocked during import | MEDIUM | Convert endpoint to `def` or add `run_in_threadpool`; no data loss; requires deploy |
| @Observable off-main-thread crash | LOW | Add `@MainActor` to import state class; no data loss |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Security scope released before upload | iOS import screen (file picker step) | Device test: log backend `len(file_bytes)` — must be > 0 |
| URLSession 60s timeout | iOS upload implementation | Integration test: 2000-film library import from production host |
| APIClient JSON vs multipart mismatch | iOS upload implementation | Network inspector: `Content-Type` must be `multipart/form-data` |
| Taste rebuild race / closed session | Backend rebuild trigger | Logs show rebuild fires after response; `taste_embedding` updated |
| @Observable background thread writes | iOS import screen (view model step) | Zero runtime thread warnings during upload in Xcode |
| UTType.zip import missing | iOS import screen (file picker step) | Compile + device test: picker shows only zip files |
| Synchronous SQLAlchemy blocking event loop | Backend production readiness | Load test: health endpoint responds during active import |
| No progress feedback | iOS upload implementation | UX review: two distinct phases visible to user |

---

## Sources

- Apple Developer Documentation: [fileImporter modifier](https://developer.apple.com/documentation/swiftui/view/fileimporter(ispresented:allowedcontenttypes:allowsmultipleselection:oncompletion:))
- Apple Developer Forums: [startAccessingSecurityScopedResource with async operations](https://developer.apple.com/forums/thread/741560)
- Apple Developer Forums: [No permission to read file when chosen with .fileImporter](https://developer.apple.com/forums/thread/748039)
- SwiftLee: [URLSession: Common pitfalls with background download & upload tasks](https://www.avanderlee.com/swift/urlsession-common-pitfalls-with-background-download-upload-tasks/)
- Apple Developer Forums: [How to get upload progress with async URLSession](https://developer.apple.com/forums/thread/698248)
- WWDC23: [Build robust and resumable file transfers](https://developer.apple.com/videos/play/wwdc2023/10006/)
- FastAPI GitHub Discussion: [Accessing dependencies in background tasks](https://github.com/fastapi/fastapi/discussions/8502)
- FastAPI GitHub Issue: [Using dependency injection to get SQLAlchemy session can lead to deadlock](https://github.com/fastapi/fastapi/issues/3205)
- Medium: [The Hidden Trap in FastAPI: Accidentally Using Sync SQLAlchemy in an Async App](https://medium.com/@patrickduch93/the-hidden-trap-in-fastapi-projects-accidently-using-sync-sql-alchemy-in-an-async-app-245b0391a17d)
- Sentry: [FastAPI: difference between run_in_executor and run_in_threadpool](https://sentry.io/answers/fastapi-difference-between-run-in-executor-and-run-in-threadpool/)
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_frontend/blnd_frontend/Networking/APIClient.swift` (JSON-only, no multipart support)
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/import_data/views.py` (async def with sync SQLAlchemy, confirmed)
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/dependencies.py` (no timeout on httpx client, get_db yields and closes)
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/import_data/workflows.py` (single db.commit() at end of run_letterboxd_import)

---
*Pitfalls research for: iOS file picker + long-running multipart upload + backend taste profile rebuild*
*Researched: 2026-03-09*
