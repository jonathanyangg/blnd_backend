# Phase 6: iOS Upload and Results - Context

**Gathered:** 2026-03-10
**Status:** Ready for planning

<domain>
## Phase Boundary

After the ZIP is captured from Letterboxd (Phase 5), upload it to the backend and show the user import results. The full flow: ZIP captured → auto-upload begins → loading screen → results with counts → Done returns to Profile. The upload endpoint already exists: `POST /import/letterboxd` (multipart file upload, returns `{ imported, skipped, failed, failed_titles }`).

</domain>

<decisions>
## Implementation Decisions

### Screen Architecture
- ImportContextView becomes a state machine with 4 states: `instructions`, `loading`, `results`, `error`
- No new views or fullScreenCovers — all states render in-place within ImportContextView
- capturedZipData (@State) already lives on ImportContextView from Phase 5 — used directly for upload

### Upload Behavior
- Upload starts automatically as soon as ZIP is captured — no confirmation step (IMPT-05)
- Re-uses capturedZipData in memory for retry — no need to re-export from Letterboxd
- Backend endpoint: `POST /import/letterboxd` with multipart file upload (not JSON — needs new APIClient method or direct URLSession call)

### Loading State
- Film.stack icon at top (same as instructions screen) for visual continuity
- Indeterminate ProgressView spinner below the icon
- Status text: "Importing your movies..."
- No progress percentage (backend processes synchronously, no streaming progress)

### Results Display
- Green checkmark.circle SF Symbol + "Import Complete" title
- Large bold imported count as hero number (e.g. "142") with "movies imported" label below
- Skipped and failed shown as smaller rows below (e.g. "3 skipped", "1 failed")
- Hide skipped/failed rows when their count is 0 — only show non-zero stats
- If failed > 0, show an inline scrollable list of failed movie titles below the counts
- AppButton "Done" at bottom

### Error State
- Error shown in-place (same state machine, not an alert)
- Error icon + error message text
- Two buttons: "Try Again" (retries upload with same ZIP data) + "Back" (returns to instructions state)
- "Try Again" goes back to loading state and re-uploads the same capturedZipData

### Navigation Flow
- "Done" pops ImportContextView entirely, returning to ProfileView
- ProfileView auto-refreshes watched/watchlist data on appear — newly imported movies show immediately in poster grid
- "Back" on error state returns to instructions state (user can re-export if needed)

### Claude's Discretion
- Exact error icon choice (SF Symbol)
- Exact error message wording
- Animation transitions between states (fade, slide, etc.)
- Multipart upload implementation details (extend APIClient or use direct URLSession)

</decisions>

<specifics>
## Specific Ideas

- The state machine approach keeps everything in ImportContextView — instructions → loading → results/error is a clean linear flow with no extra navigation layers
- The hero number pattern (big "142" + small "movies imported") is similar to how stats work on ProfileView
- Film.stack icon persists through instructions and loading states for visual continuity, then switches to checkmark on results

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `AppButton`: Use for "Done" on results and "Try Again"/"Back" on error
- `AppTheme`: Dark monochrome styling throughout (background, card, cardSecondary, textDim, textMuted)
- `film.stack` SF Symbol: Already used on ImportContextView instructions — reuse on loading state

### Established Patterns
- `APIClient.shared`: Currently JSON-only (Content-Type: application/json). Backend endpoint expects multipart/form-data file upload — will need multipart upload capability
- `@State` state machine: Common SwiftUI pattern — enum for view state, switch in body
- `ProfileView` fetches data on `.task {}` — popping back triggers re-fetch automatically

### Integration Points
- `ImportContextView.swift`: Transform from static instructions view into state machine (instructions/loading/results/error)
- `APIClient.swift` or new `ImportAPI.swift`: Add multipart file upload for `POST /import/letterboxd`
- Backend response model: `ImportSummaryResponse { imported: Int, skipped: Int, failed: Int, failed_titles: [String] }`
- `ProfileView.swift`: Verify `.task {}` re-fetches on navigation pop (should work with existing code)

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-ios-upload-and-results*
*Context gathered: 2026-03-10*
