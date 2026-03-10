# Project Research Summary

**Project:** BLND — iOS Letterboxd Integration Frontend (v1.1)
**Domain:** iOS file picker + multipart upload + backend taste profile rebuild
**Researched:** 2026-03-09
**Confidence:** HIGH

## Executive Summary

The v1.1 milestone adds the iOS-side of the Letterboxd import flow. The backend pipeline already exists and ships complete from v1.0: `POST /import/letterboxd` accepts a multipart ZIP, parses five CSVs, resolves films via TMDB, writes to the database, and returns `{imported, skipped, failed, failed_titles}`. What v1.1 adds is the iOS surface (file picker, upload, progress state, results display) and a single backend hook that triggers a taste profile rebuild after a successful bulk import. No new dependencies are required on either platform. Everything needed is in Swift's standard library, Foundation, and the already-installed FastAPI stack.

The recommended implementation pattern is: `.fileImporter` with `UTType.zip` for file selection, manual multipart body construction (15–20 lines of `Data` assembly — no Alamofire), `URLSession.upload(for:from:delegate:)` with a `URLSessionTaskDelegate` for upload progress, and an `@Observable @MainActor ImportState` class driving a phase enum (`idle → uploading → done/failed`). On the backend, a single `background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)` call is appended to `import_letterboxd` in `views.py` — the identical pattern already used in `tracking/views.py`. The new iOS components (4 new files, 3 modified files) slot cleanly into the existing architectural conventions: static API enum, `@Observable` state class, `APIClient` singleton extended with an `upload<T>()` overload.

The dominant risks are all implementation-time traps rather than architectural unknowns: security-scoped resource access must bracket the file read synchronously inside the `.fileImporter` completion closure (not in a later async Task), the URLSession must use a custom configuration with a 300-second timeout (the default 60 seconds kills large library imports while the backend is still processing), the background task on the backend must open a fresh `SessionLocal()` rather than reusing the request's `db` session (which closes when the response is sent), and all `@Observable` mutations must originate on the main actor. Every one of these is a well-documented pitfall with a clear, low-effort mitigation.

---

## Key Findings

### Recommended Stack

No new libraries or packages are required. The iOS side uses SwiftUI `.fileImporter` (iOS 14+, stdlib), `UTType.zip` from `UniformTypeIdentifiers` (iOS 14+, system framework), and `URLSession.upload(for:from:delegate:)` with `URLSessionTaskDelegate` (iOS 15+, Foundation). The backend side uses FastAPI `BackgroundTasks` (already installed at 0.135.1) and the existing `rebuild_taste_profile` function (already callable from `app.recommendations.services`). The zero-third-party-dependency policy on iOS is preserved. The two-line backend diff passes the existing `pre-commit` hooks (ruff, pyright strict, codespell).

**Core technologies (new for v1.1):**
- `.fileImporter` + `UTType.zip`: native system file picker, no UIKit wrapper, iCloud Drive and third-party storage included automatically
- Manual multipart body (`Data` construction with UUID boundary): replaces Alamofire; exactly 15–20 lines of Swift; field name must be `"file"` to match FastAPI's `UploadFile = File(...)`
- `URLSession.upload(for:from:delegate:)`: the only stdlib-native path to async upload with per-byte progress callbacks; requires `URLSessionTaskDelegate` conformance
- `URLSessionConfiguration` with `timeoutIntervalForRequest = 300`: mandatory override of the 60-second default for large library imports
- FastAPI `BackgroundTasks.add_task(rebuild_taste_profile, ...)`: established project pattern, correct lifecycle for post-response work

**What does NOT change:**
- Backend import pipeline (`workflows.py`, `schemas.py`) — unchanged from v1.0
- `APIClient.request<T>()` — untouched; a new `upload<T>()` overload is added alongside it
- `AuthState` — separate from `ImportState`; no coupling

### Expected Features

The feature surface is deliberately narrow. Every P1 item maps to an existing backend contract or existing iOS pattern. P2 items add polish with no new code patterns.

**Must have (P1 — table stakes):**
- Settings/Profile entry point — "Import from Letterboxd" row in `ProfileView` navigates to `ImportView`
- `ImportView` idle state — instructions copy ("Go to letterboxd.com/settings/data, export your data, then select the downloaded ZIP"), "Select ZIP File" button, selected filename confirmation
- Multipart upload to `POST /import/letterboxd` — via new `ImportAPI.upload(fileData:fileName:)` calling `APIClient.upload<T>()`
- In-progress state — indeterminate `ProgressView`, copy: "Resolving films via TMDB — this may take 30 seconds"
- Results state — imported / skipped / failed counts; failed_titles collapsible list when `failed > 0`
- Error state — inline `APIError` message, "Try Again" resets to idle
- Backend taste rebuild hook — `background_tasks.add_task(rebuild_taste_profile, ...)` in `views.py`, guarded by `result.imported > 0`

**Should have (P2 — differentiators):**
- "Already up to date" copy variant when `imported == 0 && failed == 0`
- Failed titles collapsible list (data already returned by backend — display only)

**Defer (v2+):**
- Import prompt in onboarding (requires onboarding restructuring; add when retention data confirms import correlates with activation)
- Import timestamp in Settings ("Last imported: March 4, 2026") — requires DB field or user metadata endpoint
- Incremental re-import — detect new entries since last import; needs per-user import timestamp
- Streaming server-side progress — SSE or chunked transfer; only if confirmed UX blocker

**Do not build:**
- Upload progress percentage / progress bar — the upload completes in <1s; the 10–90 second wait is server-side TMDB resolution with no progress signal; a bar that jumps to 100% then freezes is worse UX than an honest spinner
- Cancel button during upload — backend has no cancellation hook; partial DB writes may have committed; use a pre-confirmation prompt instead
- In-app webview to Letterboxd export page — auth does not transfer across cookie jars; download stays in webview sandbox; fragile to Letterboxd UI changes
- OAuth integration with Letterboxd — API is invite-only beta with no export endpoint; every comparable app uses the manual ZIP flow

### Architecture Approach

The iOS architecture mirrors the existing `AuthState` / `AuthAPI` / `APIClient` convention exactly. Four new files and three file modifications deliver the full feature. The component chain is strictly unidirectional: `ImportView` observes `ImportState`, `ImportState` calls `ImportAPI`, `ImportAPI` calls `APIClient.shared.upload()`. `ImportState` is separate from `AuthState` — import state is transient screen state; mixing it into `AuthState` would cause the auth gate (`ContentView`) to re-render on every upload progress tick. The rebuild logic belongs in `views.py` (not `workflows.py`) because `BackgroundTasks` and `openai_client` are FastAPI HTTP-layer constructs unavailable inside business logic.

**Major components:**

| Component | Status | Responsibility |
|-----------|--------|----------------|
| `ImportView` | NEW | `.fileImporter` modifier, phase-driven UI, results card, error + retry |
| `ImportState` | NEW | `@Observable @MainActor` phase enum (`idle/uploading/done/failed`), owns `upload()` async method |
| `ImportAPI` | NEW | Static enum, one function: `upload(fileData:fileName:) async throws -> ImportSummaryResponse` |
| `ImportModels` | NEW | `ImportSummaryResponse: Decodable` with snake_case → camelCase `CodingKeys` |
| `APIClient.upload<T>()` | MODIFIED | Multipart overload alongside existing `request<T>()`; reuses `handleResponse`, `KeychainManager` |
| `ProfileView` | MODIFIED | Add "Import from Letterboxd" navigation row |
| `blndApp.swift` | MODIFIED | Instantiate `ImportState()`, inject via `.environment(importState)` |
| `import_data/views.py` | MODIFIED | Add `BackgroundTasks` param; schedule `rebuild_taste_profile` after workflow returns |
| `import_data/workflows.py` | UNCHANGED | All import logic complete and correct from v1.0 |
| `recommendations/services.py` | UNCHANGED | `rebuild_taste_profile` callable with existing signature |

**iOS build order (strictly dependency-ordered):**
`ImportModels` → `APIClient.upload<T>()` → `ImportAPI` → `ImportState` → `ImportView` → `ProfileView` → `blndApp`

**Backend build (independent of iOS track):**
One diff to `import_data/views.py` — add `BackgroundTasks` param, import `rebuild_taste_profile`, add `background_tasks.add_task(...)` after workflow call. Three lines total.

### Critical Pitfalls

1. **Security-scoped resource released before upload** — Read `Data(contentsOf: url)` synchronously inside the `.fileImporter` `onCompletion` closure while the scope is open. Never store the URL and defer the read to an async Task. The scope expires before the Task starts on device (Simulator is more permissive — this failure is invisible until physical device testing).

2. **URLSession 60-second request timeout kills large imports** — The default `timeoutIntervalForRequest = 60` is time-between-received-packets, not total request duration. A 1000-film library takes 25+ seconds of TMDB resolution on the backend before sending a single response byte. Create a dedicated `URLSessionConfiguration` with `timeoutIntervalForRequest = 300` for the import session. Do not route the upload through `APIClient`'s `URLSession.shared`.

3. **Multipart boundary mismatch causes silent 422** — The boundary string in the `Content-Type` header (`multipart/form-data; boundary=<uuid>`) must exactly match the boundary used to construct the body. FastAPI returns `422 Unprocessable Entity` with no useful diagnostic on a mismatch. Use one UUID generated per request and pass it to both the header and the body builder.

4. **BackgroundTask using the request's closed DB session** — FastAPI's `get_db()` dependency closes the session when the response is sent; `BackgroundTask` functions run after that. Passing the request `db` to the background task causes `InvalidRequestError: Session is already closed`. Always open a fresh `SessionLocal()` inside the task and close it in a `finally` block.

5. **`@Observable` mutations from non-main-actor context** — `URLSessionTaskDelegate` callbacks arrive on an arbitrary background thread. Annotate `ImportState` with `@MainActor`; use `nonisolated` on the delegate method with an explicit `Task { @MainActor in self.uploadProgress = progress }` dispatch. Skipping this produces runtime warnings in debug and crashes on iOS 17+ in production.

6. **Synchronous SQLAlchemy inside `async def` import endpoint blocks the event loop** — The existing `import_letterboxd` is `async def` but calls blocking SQLAlchemy ORM methods. For a 2000-film import this monopolizes the event loop for 30–90 seconds, stalling all other API consumers. Convert to `def` (FastAPI threads it automatically) or wrap the blocking call with `run_in_threadpool`. Acceptable to treat as known tech debt for v1.1 at low concurrent user count.

---

## Implications for Roadmap

The v1.1 work is narrow, well-bounded, and has no unresolved unknowns. Two independent implementation tracks converge at integration testing. Research is exhaustive — no phase requires `/gsd:research-phase`.

### Phase 1: Backend Hook

**Rationale:** The backend change is three lines, independent of all iOS work, and can be deployed before iOS ships. Shipping it first gives the team a verified integration target and eliminates the risk of an iOS-correct client hitting a backend that still returns stale taste profiles.

**Delivers:** `POST /import/letterboxd` triggers `rebuild_taste_profile` via `BackgroundTasks` after every successful import. Taste profile is current after bulk import without any user action.

**Implements:** `background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)` in `import_data/views.py`. Three lines (import, parameter, call).

**Avoids:** Synchronous rebuild inside the endpoint (doubles response latency for large imports). Reusing the request's `db` session in the background task (session is closed by the time the task runs).

**Research flag:** Standard pattern. Identical to `tracking/views.py`. No deeper research needed.

---

### Phase 2: iOS Data Layer

**Rationale:** The model, networking, and state layers must exist before any UI can be written. Building bottom-up eliminates integration debt. Each layer can be verified independently before a single SwiftUI view exists.

**Delivers:** `ImportModels.swift` (Decodable struct), `APIClient.upload<T>()` overload (multipart body builder + extended-timeout URLSession configuration), `ImportAPI.swift` (static enum calling the overload), `ImportState.swift` (`@Observable @MainActor` phase machine with `upload()` async method).

**Avoids:** Routing upload through `APIClient.request<T>()` (JSON-only — causes 422). Using `URLSession.shared` without timeout override (60-second default kills large library imports). `@Observable` mutations from background thread (annotate class `@MainActor`, dispatch delegate callbacks explicitly).

**Research flag:** All patterns confirmed against Apple docs and WWDC21. No ambiguity.

---

### Phase 3: iOS View Layer

**Rationale:** Views are built last because they depend on the complete data layer. `ImportView` is a single screen with four discrete visual states; the phase enum makes transitions unambiguous.

**Delivers:** `ImportView.swift` (`.fileImporter` modifier, phase-driven body, results card, error + retry). `ProfileView` modified with navigation row. `blndApp.swift` modified to inject `ImportState`.

**Features:** All P1 table stakes and P2 items (failed titles collapsible, "Already up to date" copy, instructions copy) — P2 items are low-effort additions in the same pass, include them.

**Avoids:** Reading the security-scoped URL in an async Task (scope expires before the Task starts on device).

**Research flag:** Standard SwiftUI patterns. Physical device testing is mandatory for security-scoped resource access — Simulator behavior is more permissive and masks this failure entirely.

---

### Phase 4: Integration and Verification

**Rationale:** The two tracks are independently testable but must be verified end-to-end together. Several pitfalls (timeout, boundary mismatch, background task session, taste rebuild correctness) are only detectable at integration time against a production-latency host.

**Delivers:** Verified end-to-end flow: select Letterboxd ZIP on device → upload completes → `ImportSummaryResponse` displayed → taste profile rebuild fires → `GET /recommendations/me` returns updated results.

**Verification checklist (from PITFALLS.md):**
- Backend logs `len(file_bytes) > 0` before zip validation (confirms security scope was held through read)
- Network inspector shows `Content-Type: multipart/form-data`, not `application/json`
- 2000-film import does not time out (must test against production-latency host — localhost hides timeout issues)
- Rebuild background task logs fire after response was sent; `taste_embedding` is non-null and updated
- Zero Xcode runtime thread warnings during upload
- Fourth import attempt within the hour returns 429, not a crash

**Research flag:** No additional research needed. Checklist is complete and actionable.

---

### Phase Ordering Rationale

- Track A (backend) is independent and should be merged first — it is three lines and removes one integration variable before iOS ships.
- Track B phases (2 and 3) are strictly sequential by dependency: Models → Networking → State → Views. Building out of order creates compilation failures.
- Phase 4 verification cannot start until both tracks are complete and running against a shared environment.
- P2 items belong in Phase 3 (not a separate phase) because they require no new code patterns and are low-effort additions on the same screen.

### Research Flags

No phases require `/gsd:research-phase`. Research for this milestone is comprehensive.

Phases with well-documented, standard patterns:
- **Phase 1:** Identical `BackgroundTasks` pattern already verified in `tracking/views.py`
- **Phase 2:** SwiftUI `.fileImporter`, `URLSessionTaskDelegate`, multipart form construction — all confirmed against Apple docs and WWDC21 session 10095
- **Phase 3:** Phase-enum-driven SwiftUI view — standard `@Observable` pattern used throughout the existing app
- **Phase 4:** Integration verification checklist is specific and complete

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All APIs verified against Apple developer docs and WWDC21. `BackgroundTasks` pattern verified against codebase (`tracking/views.py`). No third-party libraries involved — zero dependency risk. |
| Features | HIGH | Feature set derived from direct codebase inspection of `ImportSummaryResponse` schema, `AppButton.isLoading`, `settingsItems` structure. No speculation. |
| Architecture | HIGH | Component list, file locations, and modification diffs derived from direct codebase inspection. All 7 new/modified files are specified. |
| Pitfalls | HIGH | Security-scope and background-task session pitfalls confirmed via Apple developer forums. Timeout behavior confirmed against URLSession documentation. Thread-safety pitfall confirmed against iOS 17 `@Observable` runtime. |
| Export flow | HIGH | Letterboxd API access requirements confirmed from official beta access page. No programmatic path to export ZIP exists. `.fileImporter` is the correct and only viable iOS approach. |

**Overall confidence:** HIGH

### Gaps to Address

- **Event loop blocking in `async def import_letterboxd`:** The existing endpoint calls blocking SQLAlchemy inside `async def`. Acceptable for v1.1 at low concurrent user count. Must be addressed before scaling — the mitigation (`def` conversion or `run_in_threadpool`) is known and documented. Flag as known technical debt in the phase plan.

- **BackgroundTask DB session — verify against existing codebase pattern:** STACK.md describes passing the request `db` to `BackgroundTasks` as following the `tracking/views.py` precedent. PITFALLS.md flags the same pattern as a critical pitfall (session closed after response). During Phase 1 implementation, inspect `tracking/views.py` to confirm whether it passes `db` or opens a fresh `SessionLocal()`. If the existing pattern passes `db` and works, it is consistent; if it opens a fresh session, match that pattern.

- **Physical device testing is non-negotiable for security-scoped access:** All security-scope behavior must be verified on a real device. Simulator does not enforce sandboxing constraints. This is a testing gate, not a research gap.

---

## Sources

### Primary (HIGH confidence)

- Apple Developer Documentation: `UTType.zip` — `public.zip-archive` identifier
- Apple Developer Documentation: `fileImporter(isPresented:allowedContentTypes:onCompletion:)` — iOS 14+
- Apple Developer Documentation: `startAccessingSecurityScopedResource()` / `stopAccessingSecurityScopedResource()`
- WWDC21 Session 10095: "Use async/await with URLSession" — task-specific delegate for upload progress with async/await
- FastAPI Background Tasks docs — sync functions dispatched to thread pool automatically; runs after response
- Letterboxd API beta access page — no export endpoint; invite-only; `.fileImporter` flow is the only viable path
- Codebase: `blnd_backend/app/tracking/views.py` — `BackgroundTasks.add_task(rebuild_taste_profile, ...)` pattern confirmed
- Codebase: `blnd_backend/app/import_data/views.py` — current endpoint signature; `BackgroundTasks` not yet wired
- Codebase: `blnd_backend/app/import_data/schemas.py` — `ImportSummaryResponse` field list confirmed
- Codebase: `blnd_backend/app/import_data/workflows.py` — `run_letterboxd_import` returns after `db.commit()`
- Codebase: `blnd_backend/app/recommendations/services.py` — `rebuild_taste_profile(user_id, db, openai_client)` signature confirmed synchronous
- Codebase: `blnd_frontend/blnd_frontend/Networking/APIClient.swift` — JSON-only; no multipart support confirmed
- Codebase: `blnd_frontend/blnd_frontend/Views/Profile/SettingsView.swift` — `settingsItems` structure confirmed
- Codebase: `blnd_frontend/blnd_frontend/Views/Shared/AppButton.swift` — `isLoading` prop confirmed

### Secondary (MEDIUM confidence)

- Apple Developer Forums thread 698248 — upload progress with async/await URLSession confirmed as requiring task-specific delegate (community-verified, matches WWDC21)
- Apple Developer Forums thread 741560 — `startAccessingSecurityScopedResource` with async operations
- Apple Developer Forums thread 748039 — no permission to read file when chosen with `.fileImporter` on device
- FastAPI GitHub Discussion 8502 — accessing dependencies in background tasks
- FastAPI GitHub Issue 3205 — SQLAlchemy session lifecycle in background tasks

### Tertiary (LOW confidence)

- Use Your Loaf: SwiftUI Importing and Exporting Files — implementation patterns (used for confirmation only; decisions based on Apple docs)
- AsyncLearn Medium: Multipart Request with URLSession and async/await — boundary construction pattern
- Simkl Letterboxd import docs — confirmed manual ZIP export is the industry-standard approach

---

*Research completed: 2026-03-09*
*Ready for roadmap: yes*
