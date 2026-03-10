# Phase 5: iOS Webview Import Flow - Research

**Researched:** 2026-03-10
**Domain:** iOS WKWebView integration, download interception, SwiftUI UIViewRepresentable
**Confidence:** HIGH

## Summary

This phase requires building an in-app WKWebView that loads Letterboxd's data export page, allows users to log in and export their data, and intercepts the resulting ZIP download -- all without leaving the BLND app. The core technical challenge is wrapping UIKit's WKWebView in SwiftUI via UIViewRepresentable with a Coordinator that implements both WKNavigationDelegate and WKDownloadDelegate to detect and capture the ZIP file download.

The WKDownloadDelegate API (available since iOS 14.5, refined in iOS 15) provides the standard mechanism for this. When the webview receives a response with a downloadable MIME type (application/zip or application/octet-stream), the navigation delegate returns `.download` policy, which triggers the WKDownloadDelegate flow. The delegate writes the file to a temporary location, then the app reads it into memory as a Swift Data object. Letterboxd exports are small (typically < 10KB, always < 1MB), so in-memory handling is safe.

The BLND codebase already has established patterns for fullScreenCover presentation (used by SearchView in HomeView), NavigationStack push (used by Settings flow), and the dark monochrome theme (AppTheme). This phase extends these patterns with one new UIKit bridge (WKWebView) and three new SwiftUI views.

**Primary recommendation:** Use UIViewRepresentable with a Coordinator class that conforms to WKNavigationDelegate + WKDownloadDelegate. Intercept downloads via `decidePolicyFor navigationResponse` returning `.download`, then capture the file in `downloadDidFinish`. Write to temp file, read into Data, clean up temp file.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Icon + "Import from Letterboxd" label in the top LEFT corner of ProfileView (mirrors settings gear in top right)
- Always visible -- does not hide after successful import
- Tapping opens a context/instructions screen via NavigationStack push (not directly to webview)
- Separate screen pushed onto ProfileView's NavigationStack (not inside the fullScreenCover)
- Step-by-step numbered instructions: 1) Log in to Letterboxd 2) Tap "Export Your Data" 3) We'll handle the rest
- Dark card styling matching AppTheme (black background, white text)
- Letterboxd logo/icon at the top for brand recognition
- "Continue" button at bottom using AppButton component
- Tapping "Continue" opens the webview as a fullScreenCover
- fullScreenCover presentation (like SearchView does)
- Minimal nav bar: X button + "Import from Letterboxd" title -- no URL bar
- Loads Letterboxd export page directly (https://letterboxd.com/settings/data/) -- Letterboxd redirects to login if not authenticated
- Confirm dismiss: if user taps X before export completes, show "Are you sure?" confirmation alert (Letterboxd login session will be lost)
- Instant transition when ZIP is intercepted -- webview closes immediately, transitions to upload/results screen (Phase 6)
- ZIP stored as in-memory Swift Data object (not temp file) -- Letterboxd exports are typically < 1MB
- If download interception fails: show error alert over the webview, user stays in webview to retry

### Claude's Discretion
- Exact icon choice for the import button (SF Symbol selection)
- Loading indicator while webview is loading the Letterboxd page
- Exact wording of the dismiss confirmation alert
- WKWebView configuration details (JavaScript, cookies, user agent)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| IMPT-01 | User can tap "Import from Letterboxd" from Profile to start the import flow | ProfileView modification: add import button to top-left of settingsRow, NavigationStack push to context screen |
| IMPT-02 | User sees an in-app webview loading Letterboxd's data export page | UIViewRepresentable wrapping WKWebView, loads https://letterboxd.com/settings/data/, presented as fullScreenCover |
| IMPT-03 | User can log into Letterboxd within the in-app webview | WKWebView with JavaScript enabled + cookies enabled via default WKWebsiteDataStore; Letterboxd redirects unauthenticated users to login automatically |
| IMPT-04 | When user taps "Export Your Data" on Letterboxd, the app intercepts the ZIP download without leaving the app | WKNavigationDelegate returns .download for zip MIME types, WKDownloadDelegate captures file to temp dir, reads into Data object |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| WebKit (WKWebView) | iOS 17+ system framework | In-app web browsing with download support | Apple's only supported webview; WKDownloadDelegate available since iOS 14.5 |
| SwiftUI (UIViewRepresentable) | iOS 17+ system framework | Bridge WKWebView into SwiftUI view hierarchy | Standard pattern for wrapping UIKit views in SwiftUI |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Foundation (Data) | System | In-memory ZIP storage | Holding downloaded ZIP data to pass to Phase 6 upload |
| Foundation (FileManager) | System | Temp file cleanup | Removing temp file after reading into Data |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| WKDownloadDelegate | URLSession manual download | Would lose cookies/auth state from webview; WKDownloadDelegate is the correct API |
| UIViewRepresentable | SFSafariViewController | Cannot intercept downloads, no custom nav bar, leaves app context |
| Temp file + read into Data | Direct in-memory download | WKDownloadDelegate API requires a file URL destination; must write then read |

**Installation:**
No additional dependencies needed. WebKit is a system framework. Import with `import WebKit`.

## Architecture Patterns

### Recommended Project Structure
```
blnd_ios/blnd_ios/
├── Views/
│   └── Import/
│       ├── ImportContextView.swift      # Pre-webview instructions screen
│       └── LetterboxdWebView.swift      # fullScreenCover with WKWebView + nav bar
├── Views/
│   └── Shared/
│       └── WebView.swift                # UIViewRepresentable + Coordinator (reusable)
└── Views/
    └── Profile/
        └── ProfileView.swift            # Modified: add import button to settingsRow
```

### Pattern 1: UIViewRepresentable with Coordinator for WKWebView
**What:** Wrap WKWebView in a SwiftUI-compatible view using UIViewRepresentable. The Coordinator class serves as both WKNavigationDelegate and WKDownloadDelegate.
**When to use:** Any time you need UIKit's WKWebView in a SwiftUI app.
**Example:**
```swift
// Source: Apple UIViewRepresentable docs + community best practices
import SwiftUI
import WebKit

struct WebView: UIViewRepresentable {
    let url: URL
    let onDownloadComplete: (Data) -> Void
    let onDownloadFailed: (Error) -> Void
    @Binding var isLoading: Bool

    func makeCoordinator() -> Coordinator {
        Coordinator(
            onDownloadComplete: onDownloadComplete,
            onDownloadFailed: onDownloadFailed,
            isLoading: $isLoading
        )
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = false
        webView.isOpaque = false
        webView.backgroundColor = .black
        webView.scrollView.backgroundColor = .black
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
```

### Pattern 2: Coordinator with Dual Delegate Conformance
**What:** Single Coordinator class implements WKNavigationDelegate (to detect downloadable responses) and WKDownloadDelegate (to handle the download).
**When to use:** When the webview needs to intercept file downloads.
**Example:**
```swift
// Source: Apple WKDownloadDelegate docs + Gualtiero Frigerio blog
class Coordinator: NSObject, WKNavigationDelegate, WKDownloadDelegate {
    let onDownloadComplete: (Data) -> Void
    let onDownloadFailed: (Error) -> Void
    @Binding var isLoading: Bool
    private var fileDestinationURL: URL?

    // MARK: - WKNavigationDelegate

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationResponse: WKNavigationResponse,
        decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void
    ) {
        if let mimeType = navigationResponse.response.mimeType,
           mimeType == "application/zip" || mimeType == "application/octet-stream"
        {
            decisionHandler(.download)
            return
        }
        decisionHandler(.allow)
    }

    func webView(
        _ webView: WKWebView,
        navigationResponse: WKNavigationResponse,
        didBecome download: WKDownload
    ) {
        download.delegate = self
    }

    // Also handle navigationAction-initiated downloads
    func webView(
        _ webView: WKWebView,
        navigationAction: WKNavigationAction,
        didBecome download: WKDownload
    ) {
        download.delegate = self
    }

    // MARK: - WKDownloadDelegate

    func download(
        _ download: WKDownload,
        decideDestinationUsing response: URLResponse,
        suggestedFilename: String,
        completionHandler: @escaping (URL?) -> Void
    ) {
        let tempDir = FileManager.default.temporaryDirectory
        let fileURL = tempDir.appendingPathComponent(suggestedFilename)
        // Remove existing file if present
        try? FileManager.default.removeItem(at: fileURL)
        fileDestinationURL = fileURL
        completionHandler(fileURL)
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let url = fileDestinationURL else { return }
        defer { try? FileManager.default.removeItem(at: url) }
        do {
            let data = try Data(contentsOf: url)
            onDownloadComplete(data)
        } catch {
            onDownloadFailed(error)
        }
    }

    func download(
        _ download: WKDownload,
        didFailWithError error: Error,
        resumeData: Data?
    ) {
        onDownloadFailed(error)
    }
}
```

### Pattern 3: fullScreenCover with Data Callback
**What:** Present the webview as a fullScreenCover from the context screen. Use a closure/binding to pass the captured ZIP data back to the parent.
**When to use:** This matches the existing SearchView pattern in HomeView.
**Example:**
```swift
// Source: Existing BLND pattern from HomeView.swift
.fullScreenCover(isPresented: $showWebView) {
    LetterboxdWebView(
        onZipCaptured: { data in
            capturedZipData = data
            showWebView = false
            // Phase 6: trigger upload
        }
    )
}
```

### Pattern 4: Confirm Dismiss with Alert
**What:** Show a confirmation alert when user taps X before export completes.
**When to use:** When the user might accidentally dismiss the webview and lose their Letterboxd login session.
**Example:**
```swift
// Source: Standard SwiftUI alert pattern
@State private var showDismissConfirm = false

Button {
    showDismissConfirm = true
} label: {
    Image(systemName: "xmark")
}
.alert("Leave Import?", isPresented: $showDismissConfirm) {
    Button("Stay", role: .cancel) {}
    Button("Leave", role: .destructive) { dismiss() }
} message: {
    Text("Your Letterboxd login session will be lost.")
}
```

### Anti-Patterns to Avoid
- **Do NOT use SFSafariViewController:** Cannot intercept downloads, shows system chrome, breaks the in-app experience.
- **Do NOT use a separate URLSession for the download:** The download needs the webview's cookie jar (user's Letterboxd auth session). WKDownloadDelegate automatically uses the webview's cookies.
- **Do NOT store the WKWebView as @State:** WKWebView is a UIKit class; it should only be created in makeUIView. Storing it in @State causes SwiftUI lifecycle issues.
- **Do NOT forget to set download.delegate = self:** In the `didBecome download` callback, the WKDownload is not automatically delegated. If you don't set it, no download methods fire.
- **Do NOT use .nonPersistent() data store:** Using `WKWebsiteDataStore.nonPersistent()` would prevent cookies from persisting during the Letterboxd login flow within the same session.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Web content rendering | Custom HTML parser/renderer | WKWebView | Full browser engine with JS, cookies, redirects |
| File download interception | URLSession + cookie extraction | WKDownloadDelegate | Automatic cookie sharing, proper download lifecycle |
| ZIP validation | Manual byte parsing | Foundation's zipfile check or let backend validate | Backend already validates via zipfile.is_zipfile |
| Letterboxd auth flow | Custom login form + API | WKWebView loading Letterboxd's own login page | Letterboxd has no public auth API; web login is the only way |

**Key insight:** The entire point of using WKWebView is to let Letterboxd handle its own authentication and export generation. We are just a container that intercepts the final download.

## Common Pitfalls

### Pitfall 1: WKDownload Delegate Not Retained
**What goes wrong:** Download starts but no delegate methods fire.
**Why it happens:** WKDownloadDelegate is NOT retained by WKDownload (unlike WKWebView retaining its navigationDelegate). If your Coordinator is deallocated, the download silently fails.
**How to avoid:** Keep a strong reference to the Coordinator (UIViewRepresentable's context.coordinator handles this automatically). Also store a strong reference to the WKDownload object itself in the Coordinator.
**Warning signs:** `downloadDidFinish` never called, no error either.

### Pitfall 2: Missing Both Download Entry Points
**What goes wrong:** Download works for some link types but not others.
**Why it happens:** There are TWO entry points for downloads: `decidePolicyFor navigationAction` returning `.download` (before server response) and `decidePolicyFor navigationResponse` returning `.download` (after server response). Each has its own `didBecome download` callback. If Letterboxd's export button triggers a navigation action (e.g., link click) rather than being caught by the response MIME type, you need to handle both.
**How to avoid:** Implement both `webView(_:navigationAction:didBecome:)` and `webView(_:navigationResponse:didBecome:)`. For the navigationAction path, also implement `decidePolicyFor navigationAction` and check if the URL contains known download patterns (e.g., "export" in the path or ".zip" extension).
**Warning signs:** Export button click loads a blank page or navigates away.

### Pitfall 3: Temp File Already Exists at Destination
**What goes wrong:** `decideDestinationUsing` completionHandler is called with a URL where a file already exists, causing the download to fail.
**Why it happens:** If user retries the export, the temp file from a previous attempt may still be there.
**How to avoid:** Remove any existing file at the destination URL before calling the completionHandler: `try? FileManager.default.removeItem(at: fileURL)`.
**Warning signs:** Download fails immediately with a file-exists error.

### Pitfall 4: WKWebView Not Showing Letterboxd Login Correctly
**What goes wrong:** Letterboxd login page doesn't render or form submission fails.
**Why it happens:** WKWebView with non-standard configuration (disabled JavaScript, restrictive content rules).
**How to avoid:** Use default WKWebViewConfiguration with `config.websiteDataStore = .default()`. JavaScript is enabled by default. Do not add content rules that block Letterboxd's scripts.
**Warning signs:** Blank page, login form not interactive, form submission shows error.

### Pitfall 5: Dismiss Confirmation Bypassed
**What goes wrong:** User swipes down to dismiss the fullScreenCover (system gesture) without seeing the confirmation alert.
**Why it happens:** fullScreenCover by default cannot be dismissed by swipe in SwiftUI (unlike .sheet). However, if the webview's scroll conflicts or custom gestures are added, unexpected dismissal can occur.
**How to avoid:** fullScreenCover already blocks swipe-to-dismiss by default. Only the X button triggers dismissal. Verify this behavior during testing.
**Warning signs:** N/A -- fullScreenCover is inherently non-swipeable.

### Pitfall 6: Letterboxd Export May Use Different MIME Types
**What goes wrong:** The MIME type check misses the download because the server sends an unexpected Content-Type.
**Why it happens:** Different servers use different MIME types for ZIP files (application/zip, application/octet-stream, application/x-zip-compressed, etc.).
**How to avoid:** Check for multiple MIME types AND check the URL/filename for `.zip` extension as a fallback. Also check the Content-Disposition header for "attachment".
**Warning signs:** Webview tries to render the ZIP file as a page (shows garbled text).

### Pitfall 7: Physical Device Required for Testing
**What goes wrong:** Download interception works in Simulator but fails on device, or vice versa.
**Why it happens:** STATE.md explicitly notes: "Physical device testing mandatory for WKDownloadDelegate -- Simulator may not enforce download interception constraints."
**How to avoid:** Test on a physical iOS device. Simulator testing is acceptable for UI layout and navigation flow, but download interception must be verified on hardware.
**Warning signs:** Download works in Simulator but not on device.

## Code Examples

Verified patterns from official sources and existing BLND codebase:

### fullScreenCover Usage (Existing Pattern)
```swift
// Source: blnd_ios/blnd_ios/Views/Home/HomeView.swift line 50
.fullScreenCover(isPresented: $showSearch) {
    NavigationStack { SearchView() }
}
```

### Settings Row Button Pattern (Existing Pattern)
```swift
// Source: blnd_ios/blnd_ios/Views/Profile/ProfileView.swift line 63-79
private var settingsRow: some View {
    HStack {
        Spacer()
        Button {
            showSettings = true
        } label: {
            Image(systemName: "gearshape")
                .font(.system(size: 20))
                .foregroundStyle(AppTheme.textDim)
        }
    }
    .padding(.top, 20)
    .padding(.horizontal, 24)
    .padding(.bottom, 16)
}
```

### NavigationStack Push Pattern (Existing Pattern)
```swift
// Source: blnd_ios/blnd_ios/Views/Profile/ProfileView.swift line 50-52
.navigationDestination(isPresented: $showSettings) {
    SettingsView()
}
```

### AppButton Usage (Existing Pattern)
```swift
// Source: blnd_ios/blnd_ios/Views/Shared/AppButton.swift
AppButton(label: "Continue") {
    showWebView = true
}
```

### Complete WKWebView Configuration for Letterboxd
```swift
// Source: Apple WKWebViewConfiguration docs + research findings
func makeUIView(context: Context) -> WKWebView {
    let config = WKWebViewConfiguration()
    // Use default (persistent) data store for cookie persistence during session
    config.websiteDataStore = .default()
    // JavaScript enabled by default -- required for Letterboxd
    // No need to set config.defaultWebpagePreferences.allowsContentJavaScript

    let webView = WKWebView(frame: .zero, configuration: config)
    webView.navigationDelegate = context.coordinator
    webView.allowsBackForwardNavigationGestures = false
    webView.isOpaque = false
    webView.backgroundColor = .black
    webView.scrollView.backgroundColor = .black

    // Load Letterboxd data export page directly
    let url = URL(string: "https://letterboxd.com/settings/data/")!
    webView.load(URLRequest(url: url))

    return webView
}
```

### MIME Type Detection for ZIP Downloads
```swift
// Source: Research findings from multiple download interception guides
private static let downloadableMIMETypes: Set<String> = [
    "application/zip",
    "application/octet-stream",
    "application/x-zip-compressed",
    "application/x-zip",
]

private func isDownloadableMIMEType(_ mimeType: String) -> Bool {
    Self.downloadableMIMETypes.contains(mimeType.lowercased())
}

private func isDownloadableURL(_ url: URL) -> Bool {
    url.pathExtension.lowercased() == "zip"
        || url.absoluteString.lowercased().contains("export")
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| URLSession manual download from webview | WKDownloadDelegate | iOS 14.5 (2021) | Native download support with automatic cookie sharing |
| UIWebView | WKWebView | iOS 8 (2014), UIWebView removed iOS 12 | UIWebView is fully deprecated and removed |
| decidePolicyFor + manual URLSession | decidePolicyFor returning .download | iOS 14.5 | Cleaner API, no cookie extraction needed |

**Deprecated/outdated:**
- UIWebView: Completely removed. Not usable.
- Manual cookie extraction from WKWebView to URLSession: No longer needed with WKDownloadDelegate.

## Open Questions

1. **Letterboxd Export MIME Type**
   - What we know: Letterboxd serves a ZIP file when the user clicks "Export Your Data". The exact Content-Type header is unknown.
   - What's unclear: Whether Letterboxd returns `application/zip`, `application/octet-stream`, or another MIME type.
   - Recommendation: Check for multiple MIME types (application/zip, application/octet-stream, application/x-zip-compressed) AND check URL pattern as fallback. Also implement the `decidePolicyFor navigationAction` path in case the export triggers via a direct link rather than a server response.

2. **Letterboxd Export Trigger Mechanism**
   - What we know: User clicks "Export Your Data" button on https://letterboxd.com/settings/data/. The download appears to be immediate (not email-based).
   - What's unclear: Whether the button triggers a form POST, a direct link to a ZIP URL, or a JavaScript-initiated download.
   - Recommendation: Handle all three cases by implementing both navigationAction and navigationResponse download paths. If JavaScript initiates the download via a blob URL, additional handling may be needed (but this is unlikely for a server-generated ZIP).

3. **Phase 6 Handoff Mechanism**
   - What we know: After ZIP capture, the webview should close and transition to Phase 6's upload/results screen.
   - What's unclear: Phase 6 is not yet implemented, so the exact handoff mechanism (how Data flows from this phase to the upload screen) is not yet defined.
   - Recommendation: Store captured Data in a @State or @Observable property on the parent view. Phase 6 will consume this. For now, Phase 5 should expose the captured Data via a completion callback and dismiss the webview.

## Sources

### Primary (HIGH confidence)
- Apple WKDownloadDelegate documentation - method signatures and lifecycle
- Apple UIViewRepresentable documentation - SwiftUI/UIKit bridge pattern
- Apple WKNavigationDelegate documentation - download policy decision handlers
- Existing BLND codebase (ProfileView.swift, HomeView.swift, SearchResultsView.swift, AppButton.swift, AppTheme.swift) - established patterns

### Secondary (MEDIUM confidence)
- [Gualtiero Frigerio - Download files in a WKWebView](https://www.gfrigerio.com/download-files-in-a-wkwebview/) - Complete WKDownloadDelegate implementation guide with code
- [Gualtiero Frigerio - DEV Community article](https://dev.to/gualtierofr/download-files-in-a-wkwebview-boo) - WKDownloadDelegate + WKNavigationDelegate patterns
- [Listy - Letterboxd export guide](https://listy.is/import/letterboxd/) - Confirmed instant download (not email-based)

### Tertiary (LOW confidence)
- Letterboxd export MIME type - could not verify the exact Content-Type header returned by Letterboxd's export endpoint; multiple MIME types should be checked as defense
- Letterboxd export trigger mechanism - could not access the page to inspect form/link behavior; implementing both download paths covers all cases

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - WKWebView + WKDownloadDelegate is the only correct approach for in-app webview with download interception on iOS; well-documented Apple API
- Architecture: HIGH - UIViewRepresentable + Coordinator is the standard and only SwiftUI/UIKit bridge pattern; fullScreenCover pattern already established in codebase
- Pitfalls: HIGH - WKDownloadDelegate pitfalls are well-documented across multiple sources; device testing requirement noted in project STATE.md
- Letterboxd-specific behavior: MEDIUM - Could not directly inspect the export page's HTML/JS; defensive multi-MIME-type checking mitigates this uncertainty

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (stable Apple APIs, unlikely to change)
