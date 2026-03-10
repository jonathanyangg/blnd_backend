# Feature Research

**Domain:** iOS file import UI + backend taste profile rebuild (v1.1 milestone)
**Researched:** 2026-03-09
**Confidence:** HIGH (codebase inspection) / MEDIUM (UX patterns from HIG + search)

---

## Scope Note

This file covers ONLY net-new features for v1.1. The backend import pipeline (ZIP parse,
TMDB resolve, DB write returning `{imported, skipped, failed, failed_titles}`) shipped in
v1.0. The iOS app has 16 screens, APIClient, and auth flow fully built. Net-new surface
area: import screen, multipart upload, in-progress state, results display, one backend hook.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| File picker for .zip selection | iOS standard: tapping a button opens Files.app to pick a file | LOW | `.fileImporter(allowedContentTypes: [UTType(filenameExtension: "zip")!])` — standard SwiftUI modifier. Must call `startAccessingSecurityScopedResource()` on result URL before reading; `stopAccessingSecurityScopedResource()` after. |
| In-progress state during upload | Users assume async ops show feedback; silent wait feels frozen | LOW | `AppButton` already supports `isLoading: true`. Import takes 5-30s (TMDB rate-limited at 25ms/call x N films). Spinner + disabled state is minimum viable feedback. |
| Results summary (imported / skipped / failed counts) | Backend returns `{imported, skipped, failed, failed_titles}` — user expects to see what happened | LOW | New results state in `ImportView`. Backend schema already defined: `ImportSummaryResponse`. Show all four fields. |
| Error handling for wrong file or network failure | User might pick a non-zip or have connectivity issues; backend returns 400 if zip is invalid | LOW | UTType filter prevents non-zip selection. Inline error state for backend rejections and `APIError` variants already used across other views. |
| Entry point in existing navigation | Import needs to live somewhere discoverable | LOW | `SettingsView` already has a placeholder list ("Account", "Notifications", "Privacy", "About"). "Import from Letterboxd" row fits here as a new navigation destination. |
| Authenticated upload | Backend `POST /import/letterboxd` requires Bearer token | LOW | `APIClient.shared` injects Bearer token. Import function follows existing `AuthAPI` / `MoviesAPI` domain API enum pattern. |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not required, but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Taste profile rebuild after import | Bulk import adds hundreds of ratings; without a rebuild the recommendation engine stays stale until user manually refreshes | MEDIUM | Backend only: add `background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)` in `import_data/views.py` after `run_letterboxd_import` returns. Mirrors the pattern already in `tracking/views.py`. iOS sees no change; this is transparent. |
| Failed titles disclosure | Shows which specific films failed TMDB resolution so user knows exactly what didn't transfer | LOW | Backend already returns `failed_titles: list[str]`. Show as collapsible list below counts when `failed > 0`. Most import tools hide this; surfacing it builds trust. |
| "Already imported" empty-state copy | Users who re-upload get `imported=0, failed=0` — without tailored copy it looks like a bug | LOW | If `imported == 0 && failed == 0`, show "Already up to date — no new films to import." Copy manages expectation without implying an error. |
| Instructions on screen | Letterboxd's export flow is non-obvious for non-power-users | LOW | Static copy: "Go to letterboxd.com/settings/data, export your data, then select the downloaded .zip file." Eliminates support friction. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Upload progress percentage / progress bar | Users expect a progress bar for long operations | The backend processes synchronously in one HTTP response. `URLSession.uploadTask` delegate only reports the data-send phase — which completes in <1s. The 5-30s wait is server-side TMDB resolution, which has no progress signal. A progress bar that jumps to 100% in 0.5s then freezes is worse than an honest spinner. | Indeterminate spinner on button + explanatory copy: "Resolving films via TMDB — this takes 10-30 seconds." |
| Re-import incremental merge | "Sync new Letterboxd entries" | Conflict resolution, deletion detection, and import-date tracking add significant complexity. Skip-on-duplicate behavior already makes re-import safe. | Show skipped count in results — re-upload is already idempotent. Incremental is a v2 concern. |
| Import via iCloud link / URL | Avoids the file picker step | Backend expects `UploadFile` (multipart). URL-based import requires a different server-side fetch flow. Files.app natively shows iCloud Drive, so users can pick the downloaded zip from iCloud without any code change. | File picker covers iCloud Drive transparently. |
| CSV-by-CSV selective import | "I only want to import ratings, not watchlist" | Backend workflow processes all five CSVs as a unit. Decomposing it adds a multi-step selection UI and significant workflow refactoring. | All-or-nothing import is correct for a migration use case. Letterboxd exports are small (typically < 500KB). |
| Cancel button during upload | User changes mind mid-import | `URLSession` cancellation is doable, but the backend has no cancellation hook — partial DB writes may have already committed. Skip logic prevents corruption but leaves an ambiguous state with no summary. | Prevent accidental start with a confirmation dialog. No cancel needed if the action is deliberate. |
| Streaming progress from server | Real-time per-film progress | Requires changing the backend endpoint from a synchronous response to a streaming response (SSE or chunked transfer). Significant backend complexity for marginal UX gain. | Defer; add if user testing shows the wait is a blocker for completion. |

---

## Feature Dependencies

```
[File picker]
    └──required by──> [Upload trigger]
                          └──required by──> [Multipart upload via ImportAPI]
                                                └──required by──> [Results display]

[Multipart upload via ImportAPI]
    NOTE: APIClient.request<T>() is JSON-only.
    A separate multipart upload method is the single implementation gap.
    Options: (a) add uploadFile() to APIClient, (b) new ImportAPI with its own URLRequest.

[Results display]
    └──enhanced by──> [Failed titles collapsible list]
    └──enhanced by──> ["Already up to date" copy variant]

[Backend taste rebuild hook]
    └──depends on──> [import endpoint completing successfully]
    └──independent of──> [iOS results display — fire-and-forget BackgroundTasks]
```

### Dependency Notes

- **File picker requires security-scoped resource access:** `startAccessingSecurityScopedResource()` / `stopAccessingSecurityScopedResource()` must wrap file data reading. Missing this causes silent permission failures on iOS 15+ when picking files from outside the app sandbox.
- **APIClient needs a multipart upload path:** The current generic `request<T: Decodable>` only supports JSON bodies. A `uploadFile(endpoint:fileData:fileName:mimeType:)` method (or dedicated `ImportAPI` struct) must build a `multipart/form-data` request manually. This is the only net-new code pattern required in iOS.
- **Taste rebuild is backend-only:** No new iOS feature needed. One `background_tasks.add_task(...)` call in `import_data/views.py`. iOS continues to receive `ImportSummaryResponse` unchanged.
- **Import screen entry point depends on SettingsView:** The "Import from Letterboxd" row is added to `settingsItems` in `SettingsView.swift` and navigates to a new `ImportView`.
- **ImportView state machine:** Three states needed — `.idle` (picker + start button), `.uploading` (spinner, disabled button), `.done(ImportSummaryResponse)` / `.error(String)`. No separate screen needed; inline state transitions work.

---

## MVP Definition

### Launch With (v1.1)

- [ ] **Settings row entry point** — "Import from Letterboxd" added to `SettingsView` settings list; navigates to `ImportView`. No new navigation infrastructure needed.
- [ ] **ImportView: idle state** — Instructions copy + "Select .zip File" button. Selected filename shown after picker completes. "Start Import" button enabled once file is selected.
- [ ] **Multipart upload to `/import/letterboxd`** — `ImportAPI.uploadZip(fileData:) async throws -> ImportSummaryResponse`. Builds multipart/form-data request manually (boundary + file part). Bearer token via existing Keychain read.
- [ ] **ImportView: uploading state** — Button enters `isLoading` state. Copy: "Resolving films via TMDB — this may take 30 seconds."
- [ ] **ImportView: results state** — Counts displayed (imported / skipped / failed). If `failed > 0`, show collapsed list of `failed_titles`. If `imported == 0 && failed == 0`, show "Already up to date" variant. Dismiss / done button returns to Settings.
- [ ] **ImportView: error state** — Inline error message surfacing `APIError` description. "Try Again" resets to idle state.
- [ ] **Backend: taste rebuild hook** — `background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)` appended to `import_letterboxd` endpoint in `import_data/views.py` after successful import.

### Add After Validation (v1.x)

- [ ] **Import prompt in onboarding** — After "You're In" screen, offer import for users migrating from Letterboxd. Add when retention data shows import correlates with activation. Requires onboarding flow change.
- [ ] **Import timestamp in Settings** — "Last imported: March 4, 2026" line below the import row. Requires a DB field or user metadata endpoint.

### Future Consideration (v2+)

- [ ] **Incremental re-import** — Detect new entries since last import. Requires per-user import timestamp + Letterboxd export date comparison.
- [ ] **Import from other sources** — Trakt, IMDb, Plex. Separate backend workflows. Defer until Letterboxd import validates the pattern.
- [ ] **Streaming progress** — SSE or chunked transfer for per-film progress. Only if the wait is a confirmed user-experience blocker.

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| File picker (.zip) | HIGH | LOW | P1 |
| Multipart upload to `/import/letterboxd` | HIGH | MEDIUM (new code pattern) | P1 |
| In-progress state (spinner + copy) | HIGH | LOW (AppButton.isLoading exists) | P1 |
| Results display (counts grid) | HIGH | LOW (schema defined) | P1 |
| Error handling + retry | HIGH | LOW (APIError pattern exists) | P1 |
| Settings entry point | HIGH | LOW (row in existing list) | P1 |
| Backend taste rebuild hook | HIGH | LOW (one add_task call) | P1 |
| Failed titles disclosure | MEDIUM | LOW (data already returned) | P2 |
| "Already up to date" copy variant | MEDIUM | LOW (conditional copy) | P2 |
| Instructions copy on ImportView | MEDIUM | LOW (static text) | P2 |
| Import prompt in onboarding | MEDIUM | HIGH (flow restructuring) | P3 |
| Upload progress percentage | LOW | HIGH + misleading | DO NOT BUILD |

**Priority key:**
- P1: Must have for v1.1 launch
- P2: Should have, add in same pass if time allows
- P3: Nice to have, future milestone
- DO NOT BUILD: Creates worse UX than the simpler alternative

---

## Competitor Feature Analysis

| Feature | Simkl (web only) | Trakt (web only) | Our Approach |
|---------|-----------------|-----------------|--------------|
| File selection | Web browse button | Upload link | iOS `.fileImporter` — native Files.app, iCloud Drive included |
| Upload feedback | Page reload, silent | Basic spinner | Inline spinner + explicit timing copy |
| Results display | Success/error message | Count summary | Counts grid + collapsible failed_titles list |
| Post-import action | Lands on profile | Stays on import page | Results state in-place; explicit dismiss |
| Taste rebuild | No recommendation engine | No recommendation engine | Background task, transparent to user |
| Native iOS experience | Web only | Web only | Native SwiftUI — no web redirect needed |

---

## Sources

- Codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/import_data/views.py` — endpoint signature, `ImportSummaryResponse` schema confirmed
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/import_data/schemas.py` — `{imported, skipped, failed, failed_titles}` confirmed
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_frontend/blnd_frontend/Networking/APIClient.swift` — JSON-only request; multipart gap confirmed
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_frontend/blnd_frontend/Views/Profile/SettingsView.swift` — `settingsItems` list structure confirmed
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_frontend/blnd_frontend/Views/Shared/AppButton.swift` — `isLoading` prop confirmed
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/tracking/views.py` — established `background_tasks.add_task(rebuild_taste_profile, ...)` pattern confirmed
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/recommendations/views.py` — `rebuild_taste_profile` function signature confirmed
- [SwiftUI Importing And Exporting Files — Use Your Loaf](https://useyourloaf.com/blog/swiftui-importing-and-exporting-files/)
- [Accessing Security Scoped Files — Use Your Loaf](https://useyourloaf.com/blog/accessing-security-scoped-files/)
- [Multipart Request with URLSession and async/await — AsyncLearn](https://asynclearn.medium.com/multipart-request-with-urlsession-and-async-await-in-swift-41b16a016cb2)
- [Building a Modern File Picker in SwiftUI with Async/Await — Gaurav Tak, Jan 2026](https://gauravtakjaipur.medium.com/building-a-modern-file-picker-in-swiftui-with-async-await-from-basics-to-production-ready-94cb8c71754c)
- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) — confirms `background_tasks.add_task` for fire-and-forget after response
- [Designing Attractive and Usable Data Importers — Smashing Magazine](https://www.smashingmagazine.com/2020/12/designing-attractive-usable-data-importer-app/)
- [Settings placement — Apple Developer Documentation](https://developer.apple.com/design/human-interface-guidelines/patterns/settings/)

---

*Feature research for: iOS Letterboxd import UI + backend taste profile rebuild (v1.1)*
*Researched: 2026-03-09*
