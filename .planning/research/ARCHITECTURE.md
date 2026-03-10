# Architecture Research

**Domain:** iOS file import UI + backend taste profile rebuild (v1.1 milestone)
**Researched:** 2026-03-09
**Confidence:** HIGH (based on direct codebase inspection of all relevant files)

## Standard Architecture

### System Overview

```
┌──────────────────────────────── iOS App ────────────────────────────────────┐
│                                                                               │
│  Views/Profile/              Networking/               State/                 │
│  ┌────────────────┐          ┌─────────────────┐       ┌─────────────────┐   │
│  │ ProfileView    │          │ ImportAPI        │       │ ImportState     │   │
│  │ (entry point)  │          │ (static enum,    │       │ (@Observable,   │   │
│  └──────┬─────────┘          │  calls           │       │  phase enum +   │   │
│         │ NavigationLink     │  APIClient.upload│       │  result counts) │   │
│         v                   └────────┬──────────┘       └────────┬────────┘   │
│  ┌────────────────┐                  │                            │            │
│  │ ImportView     │ ─── async ──→    │                            │ @Observable│
│  │ (.fileImporter │ ←── phase ──── ImportState ───────────────────┘            │
│  │  + progress    │                  │ calls APIClient.shared.upload()          │
│  │  + results)    │                  │                                          │
│  └────────────────┘          ┌───────┴──────────┐                              │
│                               │ APIClient        │                              │
│                               │ (MODIFIED:       │                              │
│                               │  + upload()      │                              │
│                               │  + multipart     │                              │
│                               │    body builder) │                              │
│                               └───────┬──────────┘                              │
└───────────────────────────────────────┼─────────────────────────────────────────┘
                                        │ POST /import/letterboxd
                                        │ multipart/form-data
                                        │ Authorization: Bearer <token>
                                        v
┌─────────────────────────────── FastAPI Backend ─────────────────────────────────┐
│                                                                                   │
│  app/import_data/                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │ views.py (MODIFIED)                                                          │ │
│  │  import_letterboxd(file, user_id, db, tmdb_client, background_tasks)        │ │
│  │    ├─ validate zip                                                            │ │
│  │    ├─ await workflows.run_letterboxd_import(...)                              │ │
│  │    └─ background_tasks.add_task(rebuild_taste_profile, user_id, db, oai)     │ │
│  └──────────────────────────────┬──────────────────────────────────────────────┘ │
│                                  │ returns ImportSummaryResponse (sync)           │
│                                  │ triggers rebuild (async, post-response)        │
│                                  │                                                │
│  ┌────────────────────┐          │  ┌──────────────────────────────────────────┐ │
│  │ workflows.py       │ ←────────┘  │ recommendations/services.py              │ │
│  │ (unchanged logic)  │             │ rebuild_taste_profile(user_id, db, oai)  │ │
│  │ run_letterboxd_    │             │   ├─ get_top_rated_movies (top 25)        │ │
│  │ import → db.commit │  BackgroundTask  ├─ compute_average_embedding           │ │
│  └────────────────────┘  ──────────────>│   (weighted avg of movie_embeddings)  │ │
│                                         │ └─ profile.taste_embedding = vector    │ │
│                                         │    db.commit()                          │ │
│                                         └──────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Status |
|-----------|----------------|--------|
| `ImportView` | File picker (`.fileImporter`), upload spinner, results summary card, error + retry | NEW |
| `ImportState` | `@Observable` class — `phase` enum: `idle/uploading/done/failed`, owns `upload()` async method | NEW |
| `ImportAPI` | Static enum — one `upload(fileData:fileName:)` func, calls `APIClient.shared.upload()` | NEW |
| `ImportModels` | `ImportSummaryResponse` — `Decodable` struct matching backend JSON | NEW |
| `APIClient.upload()` | New `multipart/form-data` method on the existing singleton; reuses `handleResponse` | MODIFIED |
| `ProfileView` | Add "Import from Letterboxd" entry point that navigates to `ImportView` | MODIFIED |
| `blndApp.swift` | Instantiate `ImportState`, inject via `.environment()` alongside `AuthState` | MODIFIED |
| `import_data/views.py` | Add `BackgroundTasks` param; after workflow returns, schedule taste rebuild | MODIFIED |
| `import_data/workflows.py` | No changes to existing logic; rebuild is NOT called here | UNCHANGED |
| `recommendations/services.py` | `rebuild_taste_profile` — already exists, no changes needed | UNCHANGED |

## Recommended Project Structure

### iOS

```
blnd_frontend/blnd_frontend/
├── App/
│   └── blndApp.swift               MODIFIED — instantiate + inject ImportState
├── Models/
│   ├── AuthModels.swift             (existing)
│   └── ImportModels.swift           NEW — ImportSummaryResponse Decodable struct
├── Networking/
│   ├── APIClient.swift              MODIFIED — add upload() + makeMultipartBody()
│   ├── AuthAPI.swift                (existing)
│   └── ImportAPI.swift              NEW — static enum, upload(fileData:fileName:)
├── State/
│   ├── AuthState.swift              (existing)
│   └── ImportState.swift            NEW — @Observable, phase enum, upload() method
└── Views/
    └── Profile/
        ├── ProfileView.swift        MODIFIED — add import entry point row
        ├── SettingsView.swift       (existing, no changes)
        └── ImportView.swift         NEW — .fileImporter + progress + results
```

### Backend

```
app/import_data/
├── views.py      MODIFIED — add BackgroundTasks, schedule rebuild after workflow
├── workflows.py  UNCHANGED — run_letterboxd_import already complete
└── schemas.py    UNCHANGED — ImportSummaryResponse already has all needed fields
```

### Structure Rationale

- **`ImportState` is a separate `@Observable` class, not merged into `AuthState`:** Import is transient screen state (active for the duration of one user interaction). `AuthState` owns session identity and persists across the app lifetime. Mixing them couples unrelated concerns and forces `ContentView`'s auth gate — which observes `AuthState` — to re-render on import progress updates. Keep them separate; inject both via `.environment()`.
- **`ImportAPI` as a static enum:** Matches `AuthAPI` exactly. One static function per backend endpoint. The enum itself has no state.
- **`ImportView` under `Views/Profile/`:** Import is an account-management action. It belongs in the Profile tab navigation stack as a pushed view, not a new tab.
- **Rebuild in `views.py`, not `workflows.py`:** `workflows.py` does not have access to `BackgroundTasks` (a FastAPI HTTP layer construct) or `openai_client` (injected at the view layer). Pushing rebuild into the workflow would require threading HTTP-layer concerns through pure business logic. The correct separation: workflow owns data transformation; view layer owns FastAPI dependencies.

## Architectural Patterns

### Pattern 1: Multipart Upload via APIClient Overload

**What:** Add a second method `upload<T: Decodable>()` to `APIClient` for `multipart/form-data` uploads. Keep it alongside the existing `request<T>()` — do not replace or modify `request<T>()`.

**When to use:** Any endpoint that accepts `UploadFile` in FastAPI. Currently only `POST /import/letterboxd`.

**Trade-offs:** A small amount of duplication vs. a unified method. At one call site, a separate named method is cleaner and immediately clear at the call site.

**Key constraint:** The FastAPI endpoint declares `file: UploadFile = File(...)`. The multipart field name must be `"file"` exactly — this is already the case in the existing `import_letterboxd` view.

**Example:**
```swift
// APIClient.swift — add alongside existing request<T>()

func upload<T: Decodable>(
    endpoint: String,
    fileData: Data,
    fileName: String,
    mimeType: String
) async throws -> T {
    guard let url = URL(string: APIConfig.baseURL + endpoint) else {
        throw APIError.invalidURL
    }
    let boundary = UUID().uuidString
    var req = URLRequest(url: url)
    req.httpMethod = "POST"
    req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
    if let token = KeychainManager.readString(key: "accessToken") {
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    }
    req.httpBody = makeMultipartBody(
        fileData: fileData, fileName: fileName, mimeType: mimeType, boundary: boundary
    )
    let (data, response): (Data, URLResponse)
    do {
        (data, response) = try await URLSession.shared.data(for: req)
    } catch {
        throw APIError.networkError(error)
    }
    guard let http = response as? HTTPURLResponse else { throw APIError.serverError(0) }
    return try handleResponse(http: http, data: data)
}

private func makeMultipartBody(
    fileData: Data, fileName: String, mimeType: String, boundary: String
) -> Data {
    var body = Data()
    let crlf = "\r\n"
    body.append("--\(boundary)\(crlf)".data(using: .utf8)!)
    body.append(
        "Content-Disposition: form-data; name=\"file\"; filename=\"\(fileName)\"\(crlf)"
            .data(using: .utf8)!
    )
    body.append("Content-Type: \(mimeType)\(crlf)\(crlf)".data(using: .utf8)!)
    body.append(fileData)
    body.append("\(crlf)--\(boundary)--\(crlf)".data(using: .utf8)!)
    return body
}
```

### Pattern 2: ImportState as @Observable Phase Machine

**What:** `ImportState` holds the current phase as an enum with associated values. `ImportView` switches on `importState.phase` to render the appropriate UI section. `ImportState.upload()` drives the phase transitions.

**When to use:** Any multi-step async UI flow with discrete, mutually exclusive visual states. Import has exactly four: nothing shown, file picker active, uploading, and terminal (success or error).

**Trade-offs:** More explicit than flat booleans + optionals, but makes impossible states unrepresentable. You cannot be simultaneously `uploading` and `done`.

**Example:**
```swift
// State/ImportState.swift

@Observable
final class ImportState {
    enum Phase {
        case idle
        case uploading
        case done(ImportSummaryResponse)
        case failed(String)
    }

    var phase: Phase = .idle

    func upload(fileData: Data, fileName: String) async {
        phase = .uploading
        do {
            let result: ImportSummaryResponse = try await ImportAPI.upload(
                fileData: fileData, fileName: fileName
            )
            phase = .done(result)
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }

    func reset() { phase = .idle }
}

// Networking/ImportAPI.swift

enum ImportAPI {
    /// Upload a Letterboxd export zip to POST /import/letterboxd.
    static func upload(fileData: Data, fileName: String) async throws -> ImportSummaryResponse {
        try await APIClient.shared.upload(
            endpoint: "/import/letterboxd",
            fileData: fileData,
            fileName: fileName,
            mimeType: "application/zip"
        )
    }
}

// Models/ImportModels.swift

struct ImportSummaryResponse: Decodable {
    let imported: Int
    let skipped: Int
    let failed: Int
    let failedTitles: [String]

    enum CodingKeys: String, CodingKey {
        case imported, skipped, failed
        case failedTitles = "failed_titles"
    }
}
```

### Pattern 3: Background Taste Rebuild in views.py (Post-Response)

**What:** After `workflows.run_letterboxd_import` returns, the view calls `background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)`. The iOS client receives `ImportSummaryResponse` immediately; the rebuild runs after FastAPI sends the response.

**When to use:** Any time a bulk write makes the taste profile stale. The import writes many rated movies at once — always warrants a rebuild. No `would_affect_top_n` guard is needed (the tracking domain uses it for single-rating events; bulk import bypasses that optimization).

**This is identical to the pattern already in `tracking/views.py`** (lines 13-18). It is not a new pattern.

**Example:**
```python
# app/import_data/views.py — diff from current

from fastapi import BackgroundTasks                    # ADD to imports
from app.recommendations.services import rebuild_taste_profile  # ADD to imports
from app.dependencies import openai_client             # already imported

@router.post("/letterboxd", response_model=ImportSummaryResponse)
@limiter.limit(LIMIT_IMPORT)
async def import_letterboxd(
    request: Request,
    background_tasks: BackgroundTasks,                 # ADD parameter
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

    # Trigger taste profile rebuild after import — same pattern as tracking/views.py
    background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)  # ADD

    return result
```

### Pattern 4: Security-Scoped Resource Access for .fileImporter

**What:** Files selected via SwiftUI's `.fileImporter` modifier are security-scoped resources. The URL is only valid while the app holds a security scope. Read the file data within the scope before dispatching the upload task.

**When to use:** Always when reading files from `.fileImporter`. Skipping `startAccessingSecurityScopedResource()` causes a silent permissions failure on device.

**Example:**
```swift
// In ImportView.swift — .fileImporter onCompletion handler

.fileImporter(
    isPresented: $showFilePicker,
    allowedContentTypes: [.zip],
    allowsMultipleSelection: false
) { result in
    switch result {
    case let .success(urls):
        guard let url = urls.first else { return }
        guard url.startAccessingSecurityScopedResource() else { return }
        defer { url.stopAccessingSecurityScopedResource() }
        guard let data = try? Data(contentsOf: url) else { return }
        let name = url.lastPathComponent
        Task { await importState.upload(fileData: data, fileName: name) }
    case .failure:
        break
    }
}
```

## Data Flow

### Full iOS Import Flow

```
User opens Profile tab
    ↓
ProfileView shows "Import from Letterboxd" row
    ↓
User taps row → NavigationLink pushes ImportView
    ↓
importState.phase == .idle → ImportView shows "Select Zip File" button
    ↓
User taps "Select Zip File" → showFilePicker = true
    ↓
.fileImporter presents UIDocumentPickerViewController (system UI)
    ↓
User selects .zip → onCompletion fires
    ↓
Read file bytes within security scope
    ↓
Task { await importState.upload(fileData: data, fileName: name) }
    ↓
importState.phase = .uploading
    ↓
ImportView shows ProgressView + "Importing your history…"
    ↓
ImportAPI.upload() → APIClient.shared.upload(endpoint: "/import/letterboxd", ...)
    ↓
URLSession sends multipart/form-data POST with Bearer token
    ↓
[Backend processes import — see backend flow below]
    ↓
Returns ImportSummaryResponse JSON
    ↓
importState.phase = .done(result)
    ↓
ImportView shows results card:
    "Imported: 423 films"
    "Skipped: 12 (already in library)"
    "Failed: 3" [with failed_titles list if any]
```

### Backend Import + Rebuild Flow

```
POST /import/letterboxd received
    ↓
import_data/views.py: validate size + zip integrity
    ↓
await workflows.run_letterboxd_import(user_id, file_bytes, db, tmdb_client)
    ├─ _parse_csvs() — extract 5 CSVs, merge by Letterboxd URI into FilmRecord dict
    ├─ Per-film loop:
    │   ├─ _resolve_tmdb_id(name, year, tmdb_client)
    │   ├─ asyncio.sleep(0.025)  [rate limit]
    │   ├─ get_movie_details(tmdb_id, db, tmdb_client)  [cache movie]
    │   ├─ INSERT WatchedMovie if in_watched or liked and not existing
    │   └─ INSERT WatchlistMovie if in_watchlist and not existing
    └─ db.commit()  ← single commit after full batch
    ↓
Returns ImportSummaryResponse to view layer
    ↓
background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)
    ↓
HTTP 200 sent to iOS client with ImportSummaryResponse
    ↓ (concurrently, in background)
rebuild_taste_profile(user_id, db, openai_client)
    ├─ get_top_rated_movies(user_id, db)  — top 25 by rating, joined with movies
    ├─ compute_average_embedding(user_id, db)  — weighted avg of movie_embeddings
    ├─ profile.taste_embedding = weighted_avg
    └─ db.commit()
    ↓
Next GET /recommendations/me uses the updated taste_embedding
```

### State Management — iOS

```
blndApp.swift creates:
    let authState = AuthState()       (existing)
    let importState = ImportState()   (NEW)

WindowGroup {
    ContentView()
        .environment(authState)
        .environment(importState)   ← add alongside existing .environment(authState)
}

ProfileView
    └─ NavigationLink → ImportView
        @Environment(ImportState.self) var importState

ImportView switches on importState.phase:
    .idle      → "Select Zip File" AppButton
    .uploading → ProgressView (indeterminate) + "Importing your history…"
    .done(r)   → Results card: r.imported / r.skipped / r.failed + failedTitles
    .failed(e) → error message + "Try Again" button calling importState.reset()
```

## Scaling Considerations

The import is user-scoped and synchronous for v1.1. The rebuild is already async (BackgroundTask).

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0-500 watched films | Current approach is fine. Import takes 5-20s. Synchronous response acceptable. |
| 500-2000 films | TMDB resolution at 25ms/call becomes the timeout risk. If needed: fire import as `asyncio.ensure_future` (202 pattern like seed-movies), poll for result. Not needed yet. |
| 100k+ users | Background worker queue (Celery/Redis). Out of scope. |

### Scaling Priorities

1. **First bottleneck:** TMDB resolution latency. A 1000-film library at 25ms/call = ~25s minimum for TMDB alone. The existing `asyncio.sleep(TMDB_RATE_LIMIT_DELAY)` in `workflows.py` is serial. If timeouts become a problem, the fix is a 202-with-polling pattern, not parallelism (TMDB rate limit makes parallelism counterproductive).
2. **Second bottleneck:** OpenAI embedding call in `rebuild_taste_profile` adds ~500ms-1s. Already handled by BackgroundTask — no client-side impact.

## Anti-Patterns

### Anti-Pattern 1: Merging ImportState into AuthState

**What people do:** Add `isImporting`, `importResult`, `importError` properties directly to `AuthState`.

**Why it's wrong:** `AuthState` is observed by `ContentView` (the auth gate) and every view that reads user identity. Adding import progress properties to it causes the entire view tree to re-render on upload progress changes. More importantly, import state is transient — it dies when the user leaves `ImportView`. Session state lives for the entire app lifetime.

**Do this instead:** A separate `ImportState` `@Observable` class injected alongside `AuthState`. Same pattern, separate concern.

### Anti-Pattern 2: Calling rebuild_taste_profile synchronously before returning the response

**What people do:** Call `services.rebuild_taste_profile(user_id, db, openai_client)` directly inside `import_letterboxd` before `return result`.

**Why it's wrong:** `rebuild_taste_profile` makes OpenAI API calls (embedding generation) that add 1-3 seconds to an already slow import response. For a 500-film library that already takes 20+ seconds, adding 3 more seconds of synchronous OpenAI calls degrades UX with no benefit to the user.

**Do this instead:** `background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)` — the exact pattern from `tracking/views.py`. The rebuild runs after the response is sent.

### Anti-Pattern 3: Triggering rebuild_taste_profile inside workflows.py

**What people do:** Add a `rebuild_taste_profile` call at the end of `run_letterboxd_import()`.

**Why it's wrong:** `workflows.py` has no access to `BackgroundTasks` (a FastAPI HTTP construct) or `openai_client` (a module-level singleton in `dependencies.py`). Putting it there requires threading HTTP-layer concerns through business logic and makes the rebuild synchronous with the response. It also violates the single-responsibility of the workflow: parse, resolve, persist. The rebuild is a side effect of the HTTP action, not of the data transformation.

**Do this instead:** The view layer handles it. `views.py` already owns all FastAPI dependencies.

### Anti-Pattern 4: Using URLSession without security-scoped resource access

**What people do:** Pass the `URL` from `.fileImporter` directly to `URLSession.shared.data(for:)` or `Data(contentsOf:)` without `startAccessingSecurityScopedResource()`.

**Why it's wrong:** Files from the document picker are in a sandboxed security scope. Attempting to read without the scope results in a permissions error that is easy to mistake for a network error.

**Do this instead:** Call `url.startAccessingSecurityScopedResource()` before reading, and `url.stopAccessingSecurityScopedResource()` in a `defer` block after.

## Integration Points

### New iOS Components

| Component | File | Integrates With |
|-----------|------|-----------------|
| `ImportState` | `State/ImportState.swift` | Injected via `.environment()` in `blndApp.swift`. Read by `ImportView`. Calls `ImportAPI`. |
| `ImportAPI` | `Networking/ImportAPI.swift` | Calls `APIClient.shared.upload()`. No other callers. |
| `ImportSummaryResponse` | `Models/ImportModels.swift` | Decoded by `APIClient.upload()`. Stored in `ImportState.phase`. Displayed by `ImportView`. |
| `APIClient.upload()` | `Networking/APIClient.swift` | New method. Reuses existing `handleResponse(http:data:)` and `KeychainManager`. |
| `ImportView` | `Views/Profile/ImportView.swift` | Pushed from `ProfileView`. Reads `importState.phase`. Fires `importState.upload()`. |

### Modified iOS Components

| Component | File | Change |
|-----------|------|--------|
| `ProfileView` | `Views/Profile/ProfileView.swift` | Add "Import from Letterboxd" navigation row. |
| `blndApp.swift` | `App/blndApp.swift` | Instantiate `ImportState()`, add `.environment(importState)`. |

### Modified Backend Components

| Component | File | Change |
|-----------|------|--------|
| `import_letterboxd` | `app/import_data/views.py` | Add `background_tasks: BackgroundTasks` parameter. Add `rebuild_taste_profile` import at top. Add `background_tasks.add_task(...)` after workflow call. Three lines total. |

### Unchanged Backend Components

| Component | File | Why Unchanged |
|-----------|------|---------------|
| `workflows.py` | `app/import_data/workflows.py` | All import logic is complete and correct. Rebuild belongs in the view layer. |
| `recommendations/services.py` | `rebuild_taste_profile` | Already exists with the exact signature needed. No changes required. |
| `schemas.py` | `app/import_data/schemas.py` | `ImportSummaryResponse` already has `imported`, `skipped`, `failed`, `failed_titles` — all fields needed by iOS. |

## Build Order

Two independent tracks converge at integration testing:

```
Track A — Backend (1 file, ~30 min)
  1. app/import_data/views.py
     - Add BackgroundTasks import and parameter
     - Add rebuild_taste_profile import
     - Add background_tasks.add_task() call after workflow returns
     Test: curl POST /import/letterboxd with a zip, confirm 200 + summary JSON,
           then wait 5s and GET /recommendations/me — taste_embedding should be fresh

Track B — iOS (dependency order matters)
  1. Models/ImportModels.swift              [NEW]
     - ImportSummaryResponse: Decodable struct (imported, skipped, failed, failedTitles)
  2. Networking/APIClient.swift             [MODIFIED]
     - Add upload<T: Decodable>() method
     - Add private makeMultipartBody() helper
  3. Networking/ImportAPI.swift             [NEW]
     - ImportAPI enum with static upload(fileData:fileName:) calling APIClient.shared.upload()
  4. State/ImportState.swift               [NEW]
     - @Observable ImportState with Phase enum and upload() async method
  5. Views/Profile/ImportView.swift        [NEW]
     - .fileImporter modifier, progress view, results card, error + retry
  6. Views/Profile/ProfileView.swift       [MODIFIED]
     - Add "Import from Letterboxd" navigation row that pushes ImportView
  7. App/blndApp.swift                     [MODIFIED]
     - Instantiate ImportState(), add .environment(importState)

Integration (after both tracks)
  8. End-to-end: select Letterboxd zip in simulator → confirm upload progress shown →
     confirm ImportSummaryResponse displayed → confirm recommendations refresh on
     next GET /recommendations/me
```

Items B1-B4 can be built and independently verified (unit tested or REPL-tested) before any UI exists. The dependency chain is strictly: Models → APIClient → ImportAPI → ImportState → ImportView. Do not build ImportView before ImportState exists.

## Sources

- Direct codebase inspection — `blnd_frontend/blnd_frontend/Networking/APIClient.swift`: confirmed `request<T>()` signature, `handleResponse(http:data:)`, `KeychainManager` usage, `APIError` enum — all reusable for the new `upload()` method
- Direct codebase inspection — `blnd_frontend/blnd_frontend/State/AuthState.swift`: confirmed `@Observable` class pattern, error string, loading state conventions
- Direct codebase inspection — `blnd_frontend/blnd_frontend/Networking/AuthAPI.swift`: confirmed static enum pattern with `async throws` functions
- Direct codebase inspection — `blnd_backend/app/tracking/views.py` lines 13-27: `_trigger_taste_rebuild()` + `BackgroundTasks.add_task()` pattern — exact precedent for the import rebuild trigger
- Direct codebase inspection — `blnd_backend/app/import_data/views.py`: confirmed current `import_letterboxd` signature; `BackgroundTasks` not yet present; the three-line diff is precisely specified
- Direct codebase inspection — `blnd_backend/app/import_data/workflows.py`: confirmed `run_letterboxd_import` returns `ImportSummaryResponse` after `db.commit()`; no rebuild call exists
- Direct codebase inspection — `blnd_backend/app/recommendations/services.py`: confirmed `rebuild_taste_profile(user_id, db, openai_client)` signature and behavior
- Direct codebase inspection — `blnd_backend/app/import_data/schemas.py`: confirmed `ImportSummaryResponse` has `imported`, `skipped`, `failed`, `failed_titles` — exact fields needed by `ImportModels.swift`
- Apple Developer Documentation (training data, HIGH confidence for stable APIs): `.fileImporter` SwiftUI modifier, `startAccessingSecurityScopedResource()` / `stopAccessingSecurityScopedResource()`, `UTType.zip`
- Apple Developer Documentation (training data, HIGH confidence): `URLSession` multipart/form-data RFC 2046 boundary format

---
*Architecture research for: iOS Letterboxd import UI + backend taste profile rebuild (v1.1)*
*Researched: 2026-03-09*
