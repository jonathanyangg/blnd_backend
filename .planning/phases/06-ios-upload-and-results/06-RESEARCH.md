# Phase 6: iOS Upload and Results - Research

**Researched:** 2026-03-10
**Domain:** SwiftUI state machines, multipart/form-data file upload, async/await networking
**Confidence:** HIGH

## Summary

This phase transforms `ImportContextView` from a static instructions screen into a four-state machine (`instructions → loading → results/error`) and adds a multipart file upload path to the networking layer. The backend endpoint (`POST /import/letterboxd`) is fully implemented and returns `{ imported, skipped, failed, failed_titles }`. The only genuinely novel work is the multipart upload: `APIClient` is currently JSON-only, so a new `ImportAPI` function must build a `multipart/form-data` request with a boundary and raw `Data` body.

Everything else maps directly onto established project patterns: `@State` enum-driven view switching, `AppButton`, `AppTheme`, SF Symbols, and `async/await` throwing functions. The hero-number stat display has a direct precedent in `ProfileView.statItem`. The `ProfileView.task {}` re-fetch-on-appear pattern means Done navigation is free — no extra code required.

**Primary recommendation:** Add a standalone `ImportAPI.swift` file with a single `upload(zipData:)` function that constructs the multipart request directly (same pattern as `AvatarUploader`), keeping `APIClient` JSON-only and preserving separation of concerns.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Screen Architecture:** ImportContextView becomes a state machine with 4 states: `instructions`, `loading`, `results`, `error`. No new views or fullScreenCovers — all states render in-place within ImportContextView.
- **Upload trigger:** Upload starts automatically as soon as ZIP is captured — no confirmation step (IMPT-05). Re-uses `capturedZipData` in memory for retry.
- **Backend endpoint:** `POST /import/letterboxd` with multipart file upload (not JSON — needs new APIClient method or direct URLSession call).
- **Loading state UI:** `film.stack` icon + indeterminate `ProgressView` spinner + "Importing your movies..." text. No progress percentage.
- **Results UI:** `checkmark.circle` SF Symbol + "Import Complete" title. Large bold imported count as hero number. Skipped/failed as smaller rows below. Hide rows when count is 0. If failed > 0, show inline scrollable list of failed titles. `AppButton "Done"` at bottom.
- **Error state UI:** Error shown in-place. Error icon + message text. Two buttons: "Try Again" (retries with same `capturedZipData`, goes back to loading) + "Back" (returns to instructions state).
- **Navigation:** "Done" pops `ImportContextView` entirely → `ProfileView` auto-refreshes via existing `.task {}`. "Back" on error returns to `instructions` state.

### Claude's Discretion

- Exact error icon choice (SF Symbol)
- Exact error message wording
- Animation transitions between states (fade, slide, etc.)
- Multipart upload implementation details (extend `APIClient` or use direct URLSession)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| IMPT-05 | After ZIP is captured, the app automatically uploads it to the backend import endpoint | `capturedZipData` already stored on `ImportContextView` from Phase 5; `.onChange` or direct callback trigger starts upload; multipart POST pattern documented below |
| IMPT-06 | User sees a loading indicator while the import is processing | `ProgressView()` with `.tint(.white)`; established pattern on `ProfileView` and `LetterboxdWebView`; state machine `.loading` case renders it |
| IMPT-07 | User sees import results (imported/skipped/failed counts) when import completes | `ImportSummaryResponse { imported, skipped, failed, failed_titles }` from backend; hero-number display mirrors `ProfileView.statItem` |
| IMPT-08 | User can tap Done to return to Profile after viewing results | `NavigationStack` pop via `@Environment(\.dismiss)` or `presentationMode`; `ProfileView.task {}` re-fetches on appear automatically |
| IMPT-09 | User sees an error message if the import fails, with ability to retry | Error state in state machine; "Try Again" re-triggers upload with existing `capturedZipData`; no Letterboxd re-export needed |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SwiftUI | iOS 17+ (project baseline) | State machine UI, layout, animation | Zero-dependency project rule |
| Foundation URLSession | iOS 17+ | Multipart file upload via `URLSession.shared.data(for:)` | Same call site as all existing networking |
| Swift Concurrency | iOS 17+ | `async/await`, `Task`, `@MainActor` | Established project convention |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| SF Symbols | iOS 17+ | `checkmark.circle`, error icon, `film.stack` | All iconography in this project uses SF Symbols |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Standalone `ImportAPI.swift` | Extend `APIClient` with a `requestMultipart` method | Either works; standalone file matches `AvatarUploader` precedent and keeps `APIClient` focused on JSON. Only meaningful if multiple multipart endpoints exist in future. |
| `withAnimation` transition | `transition(.opacity)` or `transition(.slide)` | Slide feels mechanical for this linear flow; fade (`.opacity`) is simpler and matches dark-theme aesthetic |

**Installation:** No new dependencies. Zero third-party libraries is a hard project constraint.

---

## Architecture Patterns

### Recommended Project Structure
```
blnd_ios/blnd_ios/
├── Networking/
│   └── ImportAPI.swift          # NEW: multipart POST /import/letterboxd
├── Models/
│   └── ImportModels.swift       # NEW: ImportSummaryResponse struct
└── Views/
    └── Import/
        └── ImportContextView.swift   # MODIFY: static → 4-state machine
```

### Pattern 1: SwiftUI @State Enum State Machine
**What:** A private enum defines all view states. A single `@State var viewState` drives the switch in `body`. Each case renders a different sub-view. Transitions happen by assigning a new case.

**When to use:** Linear flows where a single screen needs to show fundamentally different content (instructions, loading, results, error).

**Example — existing project precedent:**
```swift
// From: blnd_ios/blnd_ios/Views/Profile/ProfileView.swift
// ProfileTab enum driving tab picker with switch in body
private enum ProfileTab: String, CaseIterable {
    case watched = "Watched"
    case watchlist = "Watchlist"
}
@State private var selectedTab: ProfileTab = .watched

switch selectedTab {
case .watched:
    watchedGrid
case .watchlist:
    watchlistGrid
}
```

**Applied to Phase 6:**
```swift
// In ImportContextView.swift
private enum ImportViewState {
    case instructions
    case loading
    case results(ImportSummaryResponse)
    case error(String)
}

@State private var viewState: ImportViewState = .instructions
@State private var capturedZipData: Data?

var body: some View {
    switch viewState {
    case .instructions:
        instructionsView
    case .loading:
        loadingView
    case let .results(summary):
        resultsView(summary: summary)
    case let .error(message):
        errorView(message: message)
    }
}
```

### Pattern 2: Multipart File Upload (direct URLSession — mirrors AvatarUploader)
**What:** Build a `URLRequest` with `Content-Type: multipart/form-data; boundary=<UUID>`, construct the body manually with boundary delimiters and `Content-Disposition` header, send with `URLSession.shared.data(for:)`.

**When to use:** When the endpoint expects `multipart/form-data` and the upload is a raw `Data` blob already in memory.

**Example:**
```swift
// Source: mirrors pattern in AvatarUploader.swift (blnd_ios/blnd_ios/Networking/AvatarUploader.swift)
// and standard RFC 7578 multipart/form-data construction

enum ImportAPI {
    static func upload(zipData: Data) async throws -> ImportSummaryResponse {
        let url = URL(string: APIConfig.baseURL + "/import/letterboxd")!
        let boundary = UUID().uuidString

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(
            "multipart/form-data; boundary=\(boundary)",
            forHTTPHeaderField: "Content-Type"
        )
        if let token = KeychainManager.readString(key: "accessToken") {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append(
            "Content-Disposition: form-data; name=\"file\"; filename=\"export.zip\"\r\n".data(using: .utf8)!
        )
        body.append("Content-Type: application/zip\r\n\r\n".data(using: .utf8)!)
        body.append(zipData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, 200 ..< 300 ~= http.statusCode else {
            throw APIError.serverError((response as? HTTPURLResponse)?.statusCode ?? 0)
        }
        return try JSONDecoder().decode(ImportSummaryResponse.self, from: data)
    }
}
```

### Pattern 3: Automatic Upload Trigger via .onChange
**What:** After `capturedZipData` is set (when `showWebView` becomes false and `capturedZipData` is non-nil), trigger upload with `.onChange(of:)` or by calling an `async` function directly in the `onZipCaptured` callback closure.

**When to use:** When upload must start automatically without user action (IMPT-05).

**Example:**
```swift
// In the fullScreenCover callback — already the right place
.fullScreenCover(isPresented: $showWebView) {
    LetterboxdWebView { data in
        capturedZipData = data
        showWebView = false
        // viewState transition happens in .onChange below
    }
}
.onChange(of: capturedZipData) { _, newData in
    guard let zipData = newData else { return }
    viewState = .loading
    Task {
        do {
            let summary = try await ImportAPI.upload(zipData: zipData)
            viewState = .results(summary)
        } catch {
            viewState = .error(error.localizedDescription)
        }
    }
}
```

**Alternative:** Set `viewState = .loading` inside the callback itself and call a `func startUpload()` that wraps the `Task`. Either is clean; `.onChange` is more SwiftUI-idiomatic and avoids a `Task` inside a synchronous closure.

### Pattern 4: Hero Number Stats (ProfileView precedent)
**What:** Large bold number + small muted label below it, side-by-side in an HStack.

**When to use:** Displaying a primary metric prominently.

**Example:**
```swift
// Direct precedent from ProfileView.statItem
private func statItem(value: String, label: String) -> some View {
    VStack(spacing: 2) {
        Text(value)
            .font(.system(size: 20, weight: .bold))
            .foregroundStyle(.white)
        Text(label)
            .font(.system(size: 12))
            .foregroundStyle(AppTheme.textMuted)
    }
    .frame(maxWidth: .infinity)
}
```

**For results view — hero imported count:**
```swift
// Larger treatment for primary metric
VStack(spacing: 4) {
    Text("\(summary.imported)")
        .font(.system(size: 64, weight: .bold))
        .foregroundStyle(.white)
    Text("movies imported")
        .font(.system(size: 16))
        .foregroundStyle(AppTheme.textMuted)
}
```

### Pattern 5: Navigation Pop from Pushed View
**What:** `ImportContextView` is pushed onto `ProfileView`'s `NavigationStack` via `navigationDestination`. Dismissing it pops back. Use `@Environment(\.dismiss)` to programmatically pop.

**When to use:** Programmatic back-navigation from within a pushed view.

**Example:**
```swift
// In ImportContextView
@Environment(\.dismiss) private var dismiss

// On Done tap
AppButton(label: "Done") {
    dismiss()
}
```

`ProfileView` uses `.task {}` which re-fires when the view re-appears after a pop, automatically refreshing watched/watchlist counts. No additional code needed in `ProfileView`.

### Anti-Patterns to Avoid
- **Creating a new fullScreenCover for results:** All states must render in-place per locked decision. No new modal presentations.
- **Keeping APIClient JSON-only assumption broken:** Do not add `Content-Type: application/json` to the multipart request — this is the most common mistake when extending JSON-centric clients.
- **`Task { @MainActor in ... }` inside a SwiftUI `.task {}`:** For `onChange`-triggered uploads, a plain `Task {}` suffices; UI state updates on `@State` vars in SwiftUI are automatically coalesced to the main actor.
- **Re-exporting ZIP on retry:** "Try Again" must use `capturedZipData` already in memory — do not navigate back to `LetterboxdWebView`.
- **Dismissing via `NavigationLink` or `navigationDestination` logic:** Use `@Environment(\.dismiss)` — cleaner and correct for pushing patterns.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multipart body construction | Custom streaming encoder | Direct `Data` append with boundary (RFC 7578) | File is already in memory as `Data`; streaming adds complexity for no gain |
| Loading spinner | Custom animated view | `ProgressView().tint(.white)` | SwiftUI built-in; already used in `LetterboxdWebView` and `ProfileView` |
| Error message extraction | Custom error type system | `error.localizedDescription` | `APIError` already conforms to `LocalizedError`; description is human-readable |
| Animation between states | Custom UIKit transition | `withAnimation(.easeInOut(duration: 0.2))` + `transition(.opacity)` | Used for tab transitions in `ProfileView`; consistent |
| Response decoding | Manual JSON parsing | `JSONDecoder().decode(ImportSummaryResponse.self, from: data)` | Same decoder used everywhere else |

**Key insight:** The entire upload-and-display path uses the same three building blocks as the rest of the codebase — `URLSession`, `JSONDecoder`, and `@State` + `switch`. The only genuinely new surface is the multipart body construction, which is ~10 lines of RFC 7578 boilerplate.

---

## Common Pitfalls

### Pitfall 1: Missing `\r\n` in Multipart Body
**What goes wrong:** Backend receives a malformed body and returns 422 (Unprocessable Entity) or 400 (File is not a valid zip archive).
**Why it happens:** RFC 7578 requires `\r\n` (CRLF) between parts, not `\n`. Copy-pasted examples often use `\n` only.
**How to avoid:** Every boundary delimiter, header line, and blank line separator uses `\r\n`. The final closing boundary ends with `--\r\n`.
**Warning signs:** Backend logs "File is not a valid zip archive" even when the Data is a valid ZIP.

### Pitfall 2: `Content-Type` Header Overrides Boundary
**What goes wrong:** Setting `Content-Type: application/json` anywhere in the request (from a shared helper) overwrites `multipart/form-data; boundary=...`. The backend cannot find the boundary and fails to parse parts.
**Why it happens:** `APIClient.performRequest` always sets `Content-Type: application/json` at line 81. If `ImportAPI` delegates to `APIClient`, it inherits this.
**How to avoid:** `ImportAPI` builds its own `URLRequest` from scratch (same as `AvatarUploader`) and never calls through `APIClient`.
**Warning signs:** Backend returns 422 with "field required" for the `file` parameter.

### Pitfall 3: State Machine Switch Exhaustiveness
**What goes wrong:** Swift compiler error if a new enum case is added but `body` switch is not updated.
**Why it happens:** Standard Swift exhaustive switching. Not a pitfall per se — but a source of build errors during iteration.
**How to avoid:** Use an associated-value enum (`case results(ImportSummaryResponse)`, `case error(String)`) from the start. All cases handled in one switch. No `default:`.
**Warning signs:** Xcode "switch must be exhaustive" compile error.

### Pitfall 4: `.onChange(of:)` Fires on First Appear
**What goes wrong:** If `capturedZipData` has an initial non-nil value (e.g. from a previous import session), upload triggers immediately on view appear.
**Why it happens:** `.onChange` in iOS 17 receives both `oldValue` and `newValue`. If initial value is non-nil, it fires when the view first appears in some scenarios.
**How to avoid:** Guard on `oldValue == nil && newValue != nil` to ensure only the transition nil→Data triggers upload. Or set `capturedZipData = nil` on `instructions` state entry (it is `nil` by default on fresh push).
**Warning signs:** Upload starts immediately without user tapping Continue.

### Pitfall 5: swiftlint `type_body_length` (max 300 lines)
**What goes wrong:** ImportContextView grows past 300 lines, triggering swiftlint error.
**Why it happens:** 4 state views in one file is significant. Instructions view alone is ~90 lines. Loading + results + error adds ~150+ more.
**How to avoid:** Extract each state's rendered content into computed `var` properties (existing style). Keep model definitions in `ImportModels.swift`. Keep network code in `ImportAPI.swift`.
**Warning signs:** `swiftlint` pre-commit hook rejects commit with `type_body_length` violation.

### Pitfall 6: swiftformat `redundantProperty` on Response Local
**What goes wrong:** Code like `let result = try await ImportAPI.upload(...); viewState = .results(result)` — swiftformat may flag if there's only one use, but this is fine since it's not immediately returned. Real pitfall: `let x = expr; return x` patterns — return the expression directly.
**Why it happens:** swiftformat `redundantProperty` rule.
**How to avoid:** Follow existing pattern — don't assign-then-immediately-return; use assigned local variables when needed for clarity (state transitions are not returns).

---

## Code Examples

Verified patterns from existing codebase:

### ImportSummaryResponse Model
```swift
// Mirror of backend schemas.py ImportSummaryResponse
// Source: blnd_backend/app/import_data/schemas.py lines 9-13
struct ImportSummaryResponse: Decodable {
    let imported: Int
    let skipped: Int
    let failed: Int
    let failedTitles: [String]

    enum CodingKeys: String, CodingKey {
        case imported
        case skipped
        case failed
        case failedTitles = "failed_titles"
    }
}
```

### AppButton Usage — Two Buttons Side by Side
```swift
// Source: blnd_ios/blnd_ios/Views/Shared/AppButton.swift
// .ghost style for secondary action, .primary for primary
HStack(spacing: 12) {
    AppButton(label: "Back", style: .ghost) {
        viewState = .instructions
    }
    AppButton(label: "Try Again") {
        guard let zipData = capturedZipData else { return }
        viewState = .loading
        Task {
            do {
                let summary = try await ImportAPI.upload(zipData: zipData)
                viewState = .results(summary)
            } catch {
                viewState = .error(error.localizedDescription)
            }
        }
    }
}
.padding(.horizontal, 24)
```

### Conditional Row Display (hide when count is 0)
```swift
// Swift conditional view — only show when non-zero
if summary.skipped > 0 {
    statRow(count: summary.skipped, label: "skipped")
}
if summary.failed > 0 {
    statRow(count: summary.failed, label: "failed")
}
```

### Scrollable List of Failed Titles
```swift
// Inline scroll for failed_titles list
if summary.failed > 0 && !summary.failedTitles.isEmpty {
    ScrollView {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(summary.failedTitles, id: \.self) { title in
                Text(title)
                    .font(.system(size: 14))
                    .foregroundStyle(AppTheme.textMuted)
            }
        }
        .padding(16)
    }
    .frame(maxHeight: 200)
    .background(AppTheme.card)
    .clipShape(RoundedRectangle(cornerRadius: AppTheme.cornerRadiusMedium))
    .padding(.horizontal, 24)
}
```

### Dismiss via @Environment
```swift
// Source: blnd_ios/blnd_ios/Views/Friends/FriendProfileView.swift pattern
@Environment(\.dismiss) private var dismiss

AppButton(label: "Done") {
    dismiss()
}
.padding(.horizontal, 24)
.padding(.bottom, 16)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `ObservableObject` + `@Published` | `@Observable` macro | iOS 17 | Simpler syntax, no `@StateObject`/`@ObservedObject` distinction needed |
| `Combine` async | `async/await` | Swift 5.5+ | All project networking uses `async/await` |
| Multiple views + navigation | In-place state machine | — | Locked decision for this phase — single view, 4 states |

**Not deprecated/outdated for this phase:** `.onChange(of:)` with two-argument closure is the iOS 17+ form (old one-argument form is deprecated). Project targets iOS 17+, so two-argument form is correct.

---

## Open Questions

1. **Error message wording and icon**
   - What we know: "Claude's discretion" for exact copy and SF Symbol choice
   - What's unclear: Whether to show backend error detail (e.g. "File is not a valid zip archive") or a generic user-friendly message
   - Recommendation: Show a generic message ("Something went wrong. Please try again.") regardless of backend error detail — backend errors are not user-actionable. Log raw error to console.

2. **State transition animation**
   - What we know: Claude's discretion; `withAnimation` + `transition(.opacity)` is the precedent
   - What's unclear: Whether fade alone or a cross-fade (`transition(.opacity)`) feels right
   - Recommendation: Wrap state assignments in `withAnimation(.easeInOut(duration: 0.3))` and add `.transition(.opacity)` to each state's root view. Consistent with `ProfileView` tab animation.

3. **Upload task cancellation on view disappear**
   - What we know: An upload may be in-flight when the user navigates away (unlikely but possible via OS interruption)
   - What's unclear: Whether to cancel the `Task` on `.onDisappear`
   - Recommendation: Store the `Task` in a `@State var uploadTask: Task<Void, Never>?` and cancel it in `.onDisappear`. This prevents a completed upload from trying to update state on a dismissed view.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Swift Testing (Swift 6 style — `@Test`, `#expect`) |
| Config file | None — embedded in Xcode project (`blnd_iosTests/blnd_iosTests.swift`) |
| Quick run command | Build + test via Xcode (no CLI test runner configured) |
| Full suite command | `xcodebuild test -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16'` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| IMPT-05 | ZIP auto-upload triggers when capturedZipData is set | unit | Manual — requires mocking URLSession | ❌ Wave 0 |
| IMPT-06 | Loading state shows spinner + text | manual-only | Visual — requires Simulator runtime | N/A |
| IMPT-07 | Results view shows correct counts | unit | `ImportSummaryResponse` Codable decode test | ❌ Wave 0 |
| IMPT-08 | Done returns to Profile | manual-only | Navigation requires Simulator runtime | N/A |
| IMPT-09 | Error state shows with retry | manual-only | Requires live network failure simulation | N/A |

### Sampling Rate
- **Per task commit:** Build succeeds (Xcode build — no errors)
- **Per wave merge:** `xcodebuild test -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16'`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `blnd_iosTests/ImportAPITests.swift` — covers IMPT-05 (mock URLSession upload), IMPT-07 (Codable decode of `ImportSummaryResponse`)

*(Note: The existing test suite has a single placeholder test. All real behavior verification for this phase is manual — UI state machines, navigation, and network calls cannot be meaningfully unit tested without URLSession mocking infrastructure not currently in the project. The Wave 0 gap for Codable decode is optional but low-effort.)*

---

## Sources

### Primary (HIGH confidence)
- Direct codebase read — `blnd_ios/blnd_ios/Networking/APIClient.swift` — existing JSON request pattern, error types
- Direct codebase read — `blnd_ios/blnd_ios/Networking/AvatarUploader.swift` — multipart-adjacent upload pattern (raw Data POST)
- Direct codebase read — `blnd_ios/blnd_ios/Views/Import/ImportContextView.swift` — current state, `capturedZipData` @State
- Direct codebase read — `blnd_ios/blnd_ios/Views/Profile/ProfileView.swift` — hero stats pattern, `.task {}` re-fetch, navigation structure
- Direct codebase read — `blnd_ios/blnd_ios/Views/Shared/AppButton.swift` — button API (label, style, isLoading)
- Direct codebase read — `blnd_ios/blnd_ios/Theme/AppTheme.swift` — all color/spacing tokens
- Direct codebase read — `blnd_backend/app/import_data/views.py` — confirmed `POST /import/letterboxd`, `UploadFile = File(...)`, authenticated, returns `ImportSummaryResponse`
- Direct codebase read — `blnd_backend/app/import_data/schemas.py` — confirmed `ImportSummaryResponse { imported, skipped, failed, failed_titles }`
- Direct codebase read — `blnd_ios/CLAUDE.md` — project conventions (zero deps, `@Observable`, `async/await`, linting rules)

### Secondary (MEDIUM confidence)
- RFC 7578 (multipart/form-data) — CRLF boundary requirements — well-established standard, not version-sensitive

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies; everything is iOS 17 built-ins already used in the project
- Architecture: HIGH — state machine pattern and multipart upload verified against existing codebase
- Pitfalls: HIGH — CRLF multipart issue and APIClient Content-Type conflict verified from direct code inspection; type_body_length from swiftlint config in CLAUDE.md
- Backend contract: HIGH — read directly from `views.py` and `schemas.py`

**Research date:** 2026-03-10
**Valid until:** 2026-06-10 (stable — SwiftUI iOS 17, Swift Concurrency, and REST patterns)
