# Phase 5: iOS Webview Import Flow - Context

**Gathered:** 2026-03-10
**Status:** Ready for planning

<domain>
## Phase Boundary

User can reach the Letterboxd data export page inside BLND and the app captures the ZIP download automatically. The full flow: tap import button on Profile → context screen with instructions → fullScreenCover webview loads Letterboxd → user logs in and taps Export → app intercepts ZIP download. Upload and results display are Phase 6.

</domain>

<decisions>
## Implementation Decisions

### Entry Point Placement
- Icon + "Import from Letterboxd" label in the top LEFT corner of ProfileView (mirrors settings gear in top right)
- Always visible — does not hide after successful import
- Tapping opens a context/instructions screen via NavigationStack push (not directly to webview)

### Pre-Webview Context Screen
- Separate screen pushed onto ProfileView's NavigationStack (not inside the fullScreenCover)
- Step-by-step numbered instructions: 1) Log in to Letterboxd 2) Tap "Export Your Data" 3) We'll handle the rest
- Dark card styling matching AppTheme (black background, white text)
- Letterboxd logo/icon at the top for brand recognition
- "Continue" button at bottom using AppButton component
- Tapping "Continue" opens the webview as a fullScreenCover

### WebView Presentation
- fullScreenCover presentation (like SearchView does)
- Minimal nav bar: X button + "Import from Letterboxd" title — no URL bar
- Loads Letterboxd export page directly (https://letterboxd.com/settings/data/) — Letterboxd redirects to login if not authenticated
- Confirm dismiss: if user taps X before export completes, show "Are you sure?" confirmation alert (Letterboxd login session will be lost)

### Download Capture Behavior
- Instant transition when ZIP is intercepted — webview closes immediately, transitions to upload/results screen (Phase 6)
- ZIP stored as in-memory Swift Data object (not temp file) — Letterboxd exports are typically < 1MB
- If download interception fails: show error alert over the webview, user stays in webview to retry

### Claude's Discretion
- Exact icon choice for the import button (SF Symbol selection)
- Loading indicator while webview is loading the Letterboxd page
- Exact wording of the dismiss confirmation alert
- WKWebView configuration details (JavaScript, cookies, user agent)

</decisions>

<specifics>
## Specific Ideas

- The import button placement mirrors the settings gear — top left vs top right creates visual symmetry on ProfileView
- Context screen is a separate navigation step, not part of the webview presentation — this keeps the fullScreenCover purely for the webview experience
- The flow is: ProfileView → push context screen → present fullScreenCover with webview → intercept ZIP → dismiss to Phase 6 upload screen

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `AppButton`: Custom button with loading state + spinner — use for "Continue" on context screen
- `SwipeBackGestureModifier`: Re-enables edge swipe on views with hidden back button — use on context screen if back button is hidden
- `AppTheme`: Dark monochrome colors (background, cardSecondary, textDim, textMuted) — use throughout
- `ProfileView.settingsRow`: Existing pattern for top-right icon button — mirror for top-left import button

### Established Patterns
- fullScreenCover: Used by SearchView for immersive overlays — same pattern for webview
- NavigationStack push: Used by Settings flow for sub-screens — same pattern for context screen
- `@Environment(AuthState.self)`: Standard way to access auth state in views
- `APIClient.shared`: All API calls go through singleton — will need for Phase 6 upload

### Integration Points
- `ProfileView.swift`: Add import button to top-left of settingsRow (or create matching importRow)
- `MainTabView.swift`: No changes needed — ProfileView handles its own navigation
- New files needed: context screen view, webview wrapper view (UIViewRepresentable for WKWebView)
- iOS app directory is `blnd_ios/` (not `blnd_frontend/` as codebase maps reference)

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-ios-webview-import-flow*
*Context gathered: 2026-03-10*
