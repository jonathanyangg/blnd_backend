# Stack Research

**Domain:** iOS file picker + multipart upload + backend taste profile rebuild trigger
**Researched:** 2026-03-09
**Confidence:** HIGH

---

## Context: What This Covers

This is the v1.1 milestone addendum. The existing stack (FastAPI 0.135.1, SQLAlchemy 2.0.47,
SwiftUI iOS 26.2+, `@Observable`, `APIClient` singleton, zero third-party deps) is already
validated and not repeated here. This file covers only what is NEW for v1.1:

1. iOS: file picker for `.zip` files, multipart form-data upload, progress tracking, results display
2. Backend: taste profile rebuild triggered after bulk import completes

**Key finding up front:** No new dependencies are required on either platform. Everything needed
is in the Swift standard library + Foundation framework (iOS) and Python stdlib + already-installed
FastAPI/SQLAlchemy (backend).

---

## iOS Side

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| SwiftUI `.fileImporter` modifier | iOS 14+ / available on iOS 26.2 deployment target | Present system file picker sheet | Native API, no extra permissions, integrates with Files app, iCloud Drive, third-party storage providers. Single modifier on any `View`. |
| `UniformTypeIdentifiers.UTType.zip` | Built into `UniformTypeIdentifiers` framework (iOS 14+) | Restrict picker to zip archives only | `UTType.zip` is a first-class Apple-documented type (identifier: `public.zip-archive`). Verified in Apple Developer docs. Use as `allowedContentTypes: [.zip]`. |
| `url.startAccessingSecurityScopedResource()` / `stopAccessingSecurityScopedResource()` | Foundation (stdlib) | Access the security-scoped URL returned by `fileImporter` | The URL from `fileImporter` is sandbox-restricted. Must bracket `Data(contentsOf: url)` with start/stop access or the read throws a permissions error. Use `defer` to guarantee `stop` runs. |
| `URLSession.upload(for:from:delegate:)` | iOS 15+ / Foundation | Async upload with progress delegate | The `async/await` variant of `URLSession` upload. Pass a `URLSessionTaskDelegate` conforming object as the `delegate:` parameter to receive `didSendBodyData` progress callbacks. This is the only async-native way to get per-byte upload progress without Combine. Available iOS 15+, confirmed stable on iOS 17+ and 26.x. |
| `URLSessionTaskDelegate.urlSession(_:task:didSendBodyData:totalBytesSent:totalBytesExpectedToSend:)` | Foundation (stdlib) | Upload progress callbacks | Fires repeatedly during upload with running byte counts. Compute `Double(totalBytesSent) / Double(totalBytesExpectedToSend)` for a 0.0–1.0 fraction. Must annotate `@MainActor` or dispatch to main to update `@Observable` state. |
| `@Observable` + `@MainActor` | Swift 5.9+ / iOS 17+ | Upload state management (progress, phase, results) | Already the project-wide state pattern. `ImportState: @Observable` class holds `uploadProgress: Double`, `phase: ImportPhase`, and `result: ImportSummaryResponse?`. Use `@MainActor` on the class so all property mutations are on the main thread and trigger SwiftUI re-renders safely. |

### Supporting Patterns (No New Libraries)

| Pattern | Mechanism | Notes |
|---------|-----------|-------|
| Multipart form-data body construction | Manual `Data` construction with boundary string | No `Alamofire` or `MultipartFormData` library needed. 15–20 lines of Swift. Boundary is a UUID string. See pattern section below. |
| Async upload in existing `APIClient` | New method `uploadZip(endpoint:fileData:fileName:)` on `APIClient` | Keeps the singleton pattern. Method creates the multipart body, configures the `URLRequest`, then calls `URLSession.upload(for:from:delegate:)`. |
| Import results display | Decode `ImportSummaryResponse` from response body | Backend already returns `{imported, skipped, failed, failed_titles}`. Map to a summary view with three numeric pills and a collapsible failed-titles list. |

### Development Notes (iOS)

- `import UniformTypeIdentifiers` is required to use `UTType.zip`. Add to the file containing the `.fileImporter` modifier.
- `fileImporter` returns `Result<URL, Error>` in its completion. Always call `startAccessingSecurityScopedResource()` on the success URL before reading bytes.
- The file read (`Data(contentsOf:)`) is synchronous/blocking. Wrap in `Task { await MainActor.run { ... } }` or call from a background task to avoid blocking the main thread on large zips.
- `URLSession.upload(for:from:delegate:)` requires `from:` to be a `Data` object (not a file URL) when passing multipart body as pre-built `Data`. This matches the in-memory pattern used by the backend (zip is read into `Data`, wrapped in multipart form body, sent as `Data`).
- The `delegate` parameter on `URLSession.upload(for:from:delegate:)` is strongly retained by the task until completion. No risk of premature deallocation.

---

## Backend Side

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| FastAPI `BackgroundTasks` | 0.135.1 (already installed) | Trigger taste rebuild after import response is sent | The established pattern already used in `tracking/views.py` and `auth/views.py`. `background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)` runs after the HTTP response is flushed. Zero new dependencies. |
| `recommendations.services.rebuild_taste_profile` | (existing function) | Perform the actual taste profile rebuild | Already implemented, synchronous, takes `(user_id, db, openai_client)`. The exact same function already called from tracking and auth endpoints. Import pattern is already established in `tracking/views.py` as a deferred import to avoid circular imports. |

### What Changes on the Backend

The import endpoint at `POST /import/letterboxd` in `app/import_data/views.py` needs exactly two additions:

1. Add `background_tasks: BackgroundTasks` as a FastAPI dependency parameter.
2. After `result = await workflows.run_letterboxd_import(...)`, call `background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)` — but only if `result.imported > 0` (no point rebuilding if nothing was imported).

No new functions, no new files, no new packages.

### Why BackgroundTasks (not asyncio.create_task)

The project already uses `asyncio.ensure_future()` for the seed pipeline (fires completely detached
from the request context) and `BackgroundTasks` for taste rebuilds (tied to the request lifecycle,
uses the same `db` session the request already has). For taste rebuild on import, `BackgroundTasks`
is correct because:

- The `db` session passed to `rebuild_taste_profile` is the same `get_db`-injected session — still
  valid when the background task runs (Starlette keeps it open until background tasks complete).
- `rebuild_taste_profile` is synchronous (no `async def`) — `BackgroundTasks` dispatches it to a
  thread pool automatically when the function is not a coroutine.
- `asyncio.create_task` with a sync function would fail; `ensure_future` has the same problem and
  also detaches from the session lifecycle.

**MEDIUM confidence note:** There is a subtle risk: `BackgroundTasks` keeps the DB session open
until the task completes. `rebuild_taste_profile` calls OpenAI (network I/O, potentially 2–5s).
This is an acceptable tradeoff at current scale — it is the same pattern already used for genre
updates and rating changes, which are also OpenAI-backed. If session contention becomes a problem
at scale, the mitigation is to open a fresh `SessionLocal()` inside the background task and close
it in a `finally` block (the same pattern as `_run_seed_pipeline_async` in `import_data/views.py`).

---

## Recommended Stack

### Core Technologies (NEW for v1.1)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| SwiftUI `.fileImporter` | iOS 14+ (stdlib) | Zip file picker | Zero deps, native system UI, handles iCloud/third-party storage. |
| `UTType.zip` (UniformTypeIdentifiers) | iOS 14+ (stdlib) | Restrict picker to zip only | Apple first-party UTI for public.zip-archive. Confirmed in Apple docs. |
| `Foundation.URLSession.upload(for:from:delegate:)` | iOS 15+ (stdlib) | Async upload with progress | Only stdlib-native way to get upload progress with async/await. |
| `URLSessionTaskDelegate` | iOS 15+ (stdlib) | Per-byte upload progress callbacks | Receives `didSendBodyData` during upload. Pass as `delegate:` to upload call. |
| FastAPI `BackgroundTasks` | 0.135.1 (already installed) | Trigger taste rebuild post-import | Established project pattern, correct lifecycle for same-session rebuild. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| None | — | — | No new libraries needed on either platform. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Xcode (existing) | iOS build, SwiftLint/SwiftFormat pre-commit | swiftlint max line 120, swiftformat before-first wrapping — already configured |
| `pre-commit run --all-files` (existing) | ruff, pyright, codespell on backend changes | The 2-line change to `import_data/views.py` must pass pyright strict mode |

---

## Installation

```bash
# iOS: No new packages. UniformTypeIdentifiers and Foundation are system frameworks.
# Add import to Swift files that use them:
#   import UniformTypeIdentifiers   (for UTType.zip)
#   import Foundation               (already imported everywhere)

# Backend: No new packages.
# The one code change is in app/import_data/views.py — add BackgroundTasks param.
# rebuild_taste_profile is already importable from app.recommendations.services.
```

---

## Key Implementation Patterns

### Pattern 1: iOS File Picker (fileImporter)

```swift
import SwiftUI
import UniformTypeIdentifiers

struct ImportView: View {
    @State private var showFilePicker = false
    @State private var importState = ImportState()

    var body: some View {
        Button("Import from Letterboxd") {
            showFilePicker = true
        }
        .fileImporter(
            isPresented: $showFilePicker,
            allowedContentTypes: [.zip]
        ) { result in
            switch result {
            case .success(let url):
                Task { await importState.upload(url: url) }
            case .failure(let error):
                importState.errorMessage = error.localizedDescription
            }
        }
    }
}
```

**Why:** `.fileImporter` with `allowedContentTypes: [.zip]` restricts the picker to zip archives
using the native `public.zip-archive` UTI. No `UIDocumentPickerViewController` wrappers needed —
`fileImporter` is the SwiftUI-native equivalent introduced in iOS 14.

### Pattern 2: Security-Scoped URL + Data Read

```swift
func readZipData(from url: URL) throws -> Data {
    guard url.startAccessingSecurityScopedResource() else {
        throw ImportError.accessDenied
    }
    defer { url.stopAccessingSecurityScopedResource() }
    return try Data(contentsOf: url)
}
```

**Why:** The URL returned by `fileImporter` is security-scoped to the sandbox. Reading without
`startAccessingSecurityScopedResource()` throws a permissions error. `defer` guarantees the
resource is released even if `Data(contentsOf:)` throws.

### Pattern 3: Multipart Form-Data Body (No Library)

```swift
func buildMultipartBody(
    fileData: Data,
    fileName: String,
    boundary: String
) -> Data {
    var body = Data()
    let crlf = "\r\n"
    body.append("--\(boundary)\(crlf)".data(using: .utf8)!)
    body.append(
        "Content-Disposition: form-data; name=\"file\"; filename=\"\(fileName)\"\(crlf)".data(using: .utf8)!
    )
    body.append("Content-Type: application/zip\(crlf)\(crlf)".data(using: .utf8)!)
    body.append(fileData)
    body.append("\(crlf)--\(boundary)--\(crlf)".data(using: .utf8)!)
    return body
}
```

**Why:** The backend expects `multipart/form-data` with field name `file` (matches FastAPI
`UploadFile = File(...)`). This is the exact wire format FastAPI's `python-multipart` parses.
The boundary is a UUID string — random per request, included in the `Content-Type` header.

### Pattern 4: Async Upload with Progress

```swift
@Observable
@MainActor
final class ImportState: NSObject, URLSessionTaskDelegate {
    var uploadProgress: Double = 0.0
    var phase: ImportPhase = .idle
    var result: ImportSummaryResponse?
    var errorMessage: String?

    func upload(url: URL) async {
        phase = .uploading
        do {
            let fileData = try readZipData(from: url)
            let boundary = UUID().uuidString
            let body = buildMultipartBody(
                fileData: fileData, fileName: url.lastPathComponent, boundary: boundary
            )
            var request = URLRequest(url: URL(string: APIConfig.baseURL + "/import/letterboxd")!)
            request.httpMethod = "POST"
            request.setValue(
                "multipart/form-data; boundary=\(boundary)",
                forHTTPHeaderField: "Content-Type"
            )
            if let token = KeychainManager.readString(key: "accessToken") {
                request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }
            let (data, response) = try await URLSession.shared.upload(
                for: request, from: body, delegate: self
            )
            // handle response...
        } catch { ... }
    }

    // URLSessionTaskDelegate — called on an arbitrary queue, dispatch to main
    nonisolated func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didSendBodyData bytesSent: Int64,
        totalBytesSent: Int64,
        totalBytesExpectedToSend: Int64
    ) {
        let progress = Double(totalBytesSent) / Double(totalBytesExpectedToSend)
        Task { @MainActor in self.uploadProgress = progress }
    }
}
```

**Why:** `URLSession.upload(for:from:delegate:)` is the iOS 15+ API that bridges async/await with
delegate-based progress. The `delegate:` parameter is strongly held by the task, so no retain
cycle or premature deallocation issues. `nonisolated` on the delegate method is required because
`URLSessionTaskDelegate` callbacks come on an arbitrary (non-main) thread; the explicit
`Task { @MainActor in ... }` dispatch to main ensures `@Observable` mutations are safe.

`ImportState: NSObject` is required because `URLSessionTaskDelegate` inherits from `NSObjectProtocol`.
This is the only reason for `NSObject` — it does not add Objective-C bridging overhead.

### Pattern 5: Backend Taste Rebuild Trigger

```python
# In app/import_data/views.py — diff from current:

@router.post("/letterboxd", response_model=ImportSummaryResponse)
@limiter.limit(LIMIT_IMPORT)
async def import_letterboxd(
    request: Request,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks,        # ADD THIS
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

    # ADD THIS — only rebuild if import actually wrote new data
    if result.imported > 0:
        from app.recommendations.services import rebuild_taste_profile
        background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)

    return result
```

**Why:** `BackgroundTasks` is the right mechanism here: it uses the same `db` session (already
open, safe for the task's lifetime), `rebuild_taste_profile` is synchronous so Starlette dispatches
it to a thread pool, and it mirrors the exact pattern in `tracking/views.py`. The `result.imported > 0`
guard prevents a pointless OpenAI + pgvector rebuild when the import had nothing new (all skipped).

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `.fileImporter` modifier | `UIDocumentPickerViewController` wrapped in `UIViewControllerRepresentable` | Never for this project — `fileImporter` is the SwiftUI-native equivalent since iOS 14 and the project has no UIKit views |
| `URLSession.upload(for:from:delegate:)` with progress delegate | `URLSession.upload(for:from:)` (no delegate) | When upload progress display is not needed — the simpler API returns `(Data, URLResponse)` directly |
| `URLSession.upload(for:from:delegate:)` with progress delegate | Combine `URLSession.DataTaskPublisher` | When project already uses Combine — this project uses `async/await` throughout and has zero Combine usage; mixing would be inconsistent |
| Manual multipart body construction | Alamofire / Moya | Never for this project — zero third-party dependency policy. 15 lines of `Data` construction replaces the library. |
| `BackgroundTasks.add_task(rebuild_taste_profile, ...)` | `asyncio.create_task` with fresh session | If `rebuild_taste_profile` becomes async (coroutine) or if session lifetime becomes a concern at scale; use the `_run_seed_pipeline_async` pattern with `SessionLocal()` in `finally` |
| `BackgroundTasks.add_task(rebuild_taste_profile, ...)` | ARQ / Celery / Redis queue | When taste rebuilds become too slow for in-process background tasks (>30s), or when you need retry/scheduling. Current rebuild is ~2–5s synchronous I/O. Overkill for current scale. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Alamofire / Moya for multipart upload | Violates the zero third-party iOS dependencies policy. 15 lines of stdlib `Data` construction replaces it entirely. | Manual multipart body + `URLSession.upload(for:from:delegate:)` |
| `UIDocumentPickerViewController` | UIKit wrapper adds 40+ lines of boilerplate for functionality that `.fileImporter` provides in 5 lines. | SwiftUI `.fileImporter` modifier |
| `URLSession.shared.data(for:)` (existing `APIClient.request`) for file uploads | The existing `request<T>` method sets `Content-Type: application/json` and encodes a JSON body. Multipart uploads require a different content type and body format. Reusing it would require special-casing. | New `uploadZip` method on `APIClient` that explicitly builds multipart body |
| Skipping security scoped resource access | Reading a security-scoped URL without `startAccessingSecurityScopedResource()` throws on device (works only in Simulator where sandbox is relaxed). | Always bracket with start/stop access; use `defer` for stop |
| `asyncio.ensure_future` for taste rebuild | Already flagged in codebase: `ensure_future` may block the endpoint in FastAPI's execution model. `BackgroundTasks` is the validated pattern for this codebase. | `BackgroundTasks.add_task` |
| Unconditional taste rebuild (no `result.imported > 0` guard) | If import yields zero new entries, calling OpenAI + pgvector rebuild wastes ~$0.001 per call and adds 2–5s of background load for no gain. | Guard with `if result.imported > 0` |

---

## Version Compatibility

| Package | Version | Compatible With | Notes |
|---------|---------|-----------------|-------|
| SwiftUI `.fileImporter` | iOS 14+ | iOS 26.2 (project target) | Stable since iOS 14; no breaking changes in iOS 15–26 |
| `UTType.zip` | iOS 14+ | iOS 26.2 (project target) | `UniformTypeIdentifiers` framework, system-linked |
| `URLSession.upload(for:from:delegate:)` | iOS 15+ | iOS 26.2 (project target) | Task-specific delegate parameter added in iOS 15 (WWDC21); stable |
| FastAPI `BackgroundTasks` | 0.135.1 | SQLAlchemy 2.0.47, Starlette 0.52.1 | Already used in 3 other endpoint files in this codebase |
| `rebuild_taste_profile` | existing | `openai==2.24.0`, `numpy==2.4.2` | Already installed and callable; synchronous; thread-pool safe |

---

## Sources

- Apple Developer Documentation: `UTType.zip` — `public.zip-archive` identifier confirmed — HIGH confidence
  (https://developer.apple.com/documentation/uniformtypeidentifiers/uttype-swift.struct/zip)
- Apple Developer Documentation: `fileImporter(isPresented:allowedContentTypes:onCompletion:)` — iOS 14+, `allowedContentTypes` array of UTType — HIGH confidence
  (https://developer.apple.com/documentation/swiftui/view/fileimporter(ispresented:allowedcontenttypes:oncompletion:))
- WWDC21 "Use async/await with URLSession" (session 10095) — task-specific delegate for upload progress with async/await — HIGH confidence
  (https://developer.apple.com/videos/play/wwdc2021/10095/)
- Apple Developer Forums thread 698248 — upload progress with async/await URLSession confirmed as requiring task-specific delegate — MEDIUM confidence (community-verified, matches WWDC21 docs)
- FastAPI `BackgroundTasks` docs — runs after response, sync functions dispatched to thread pool — HIGH confidence
  (https://fastapi.tiangolo.com/tutorial/background-tasks/)
- Codebase inspection — `app/tracking/views.py`, `app/auth/views.py`: `BackgroundTasks.add_task(rebuild_taste_profile, ...)` pattern verified — HIGH confidence
- Codebase inspection — `app/recommendations/services.py`: `rebuild_taste_profile(user_id, db, openai_client)` signature confirmed synchronous — HIGH confidence
- Codebase inspection — `app/import_data/views.py`: current endpoint signature, confirmed `BackgroundTasks` not yet wired — HIGH confidence
- `requirements.txt` inspection — FastAPI 0.135.1, SQLAlchemy 2.0.47, openai 2.24.0 — HIGH confidence

---

*Stack research for: iOS file picker + multipart upload + backend taste profile rebuild (v1.1)*
*Researched: 2026-03-09*
