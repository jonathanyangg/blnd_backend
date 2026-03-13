# Phase 8: iOS Shared Component Extraction - Research

**Researched:** 2026-03-12
**Domain:** SwiftUI component extraction / refactoring (iOS 17+, Swift 5.9)
**Confidence:** HIGH

---

## Summary

Phase 8 is a pure refactoring phase with zero new behaviour. Three private helpers
(`posterTile`, `statsRow`/`statItem`, and the `LazyVGrid` grid setup) are promoted
from private members of `ProfileView` to public, standalone structs in
`Views/Shared/`. The refactored `ProfileView` must compile and behave identically
after the change. `FriendProfileView` (and every future view) can then import these
components without duplicating code.

The extraction follows the exact same pattern already used in this codebase: atomic
SwiftUI `View` structs in `Views/Shared/`, passing all data as `let` properties, no
`@State` inside the component unless it owns internal interaction state. The grid
helper (`PosterGrid`) is thin — it just wraps `LazyVGrid` with the project's
standard three-column layout and standard horizontal padding. All three components
must pass data in, not reach into any parent state object.

Because this is a refactor, the primary success criterion is compile-time and visual
parity: `ProfileView` looks and behaves identically before and after the change. The
Xcode simulator is the test harness. There are no automated unit tests in this
codebase; the test suite is a single empty `@Test func example()`.

**Primary recommendation:** Extract `PosterTile`, `StatsRow`, and `PosterGrid` as
pure `View` structs in `Views/Shared/`. Pass data in as `let` properties. Keep
`ProfileView` visually and behaviourally identical. No other files need to change in
this phase.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| IOS-06 | PosterTile and StatsRow extracted as shared components used by both ProfileView and FriendProfileView | Extraction strategy documented below; interface designs confirmed from source inspection |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SwiftUI | iOS 17+ | Declarative UI | Project-wide standard, zero third-party deps |
| Swift | 5.9 (`.swiftformat`) | Language | Project standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| AsyncImage | built-in (iOS 15+) | Remote poster images | Already used in `posterTile` and `MovieCard` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pure `View` structs | `ViewBuilder` free functions | Structs are the project convention; previews are trivial to add; free functions can't be extended later |
| Standalone file per component | One combined `SharedComponents.swift` | Project already gives each shared component its own file; keep pattern |

**Installation:** No new dependencies. Zero third-party dependencies is a hard project constraint.

---

## Architecture Patterns

### Recommended Project Structure
```
Views/Shared/
├── AppButton.swift
├── AvatarView.swift
├── CastSectionView.swift
├── GenrePill.swift
├── MovieCard.swift             <- reference pattern for PosterTile
├── OnboardingProgressBar.swift
├── PosterGrid.swift            <- NEW (Wave 1 deliverable)
├── PosterTile.swift            <- NEW (Wave 1 deliverable)
├── SearchBar.swift
├── StarRatingInput.swift
├── StatsRow.swift              <- NEW (Wave 1 deliverable)
├── SwipeBackGesture.swift
├── TasteMatchBadge.swift
├── WatchlistPickerSheet.swift
└── WebView.swift
```

### Pattern 1: Pure View Struct in Views/Shared/

**What:** A self-contained SwiftUI `View` struct with `let` properties for all data
it needs. No `@EnvironmentObject`, no `@Observable` state injection — just plain
value inputs.

**When to use:** Any visual piece used by more than one view, or any visual piece
large enough that extracting it makes a parent view's `body` readable at a glance.

**Reference:** `MovieCard.swift` and `AvatarView.swift` — these are the canonical
patterns in this codebase.

```swift
// Source: blnd_ios/blnd_ios/Views/Shared/MovieCard.swift
struct MovieCard: View {
    var title: String?
    var posterPath: String?
    var width: CGFloat = 90
    // ...defaults for optional visual config

    var body: some View { /* ... */ }
}
```

### Pattern 2: PosterTile Interface Design

**Source of truth:** `ProfileView.posterTile(path:rating:)` (lines 251–290 of
`ProfileView.swift`).

The extracted struct must accept the same two inputs:

```swift
// Extracted to Views/Shared/PosterTile.swift
struct PosterTile: View {
    let posterPath: String?
    let rating: Double?

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            // AsyncImage or gradient placeholder
            // Rating capsule badge (bottomTrailing, optional)
        }
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}
```

Naming note: `posterPath` (not `path`) matches the field name on `WatchedMovieResponse`
and `WatchlistMovieResponse`, making call sites self-documenting:

```swift
PosterTile(posterPath: movie.posterPath, rating: movie.rating)
```

### Pattern 3: StatsRow Interface Design

**Source of truth:** `ProfileView.statsRow` (lines 118–152) and `ProfileView.statItem`
(lines 142–152).

`statsRow` in `ProfileView` is tightly coupled to `TabState` (tapping Friends/Blends
stats switches tabs). `FriendProfileView` will need a stats row that navigates
differently (IOS-04: tap friend's friends count → open their friends list). Providing
a generic callback-based interface avoids baking navigation logic into the component:

```swift
// Extracted to Views/Shared/StatsRow.swift
struct StatItem {
    let label: String
    let value: Int
    let onTap: (() -> Void)?   // nil = not tappable
}

struct StatsRow: View {
    let items: [StatItem]

    var body: some View {
        HStack {
            ForEach(items.indices, id: \.self) { i in
                statCell(items[i])
            }
        }
        .padding(.vertical, 16)
        .overlay(alignment: .top)  { Divider().background(AppTheme.cardSecondary) }
        .overlay(alignment: .bottom) { Divider().background(AppTheme.cardSecondary) }
        .padding(.horizontal, 24)
        .padding(.bottom, 20)
    }

    private func statCell(_ item: StatItem) -> some View {
        let content = VStack(spacing: 2) {
            Text("\(item.value)")
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(.white)
            Text(item.label)
                .font(.system(size: 12))
                .foregroundStyle(AppTheme.textMuted)
        }
        .frame(maxWidth: .infinity)

        if let onTap = item.onTap {
            return AnyView(Button { onTap() } label: { content }.buttonStyle(.plain))
        } else {
            return AnyView(content)
        }
    }
}
```

`ProfileView` then constructs the items array inline:

```swift
StatsRow(items: [
    StatItem(label: "Watched",   value: watchedTotal,    onTap: nil),
    StatItem(label: "Watchlist", value: watchlistTotal,  onTap: nil),
    StatItem(label: "Friends",   value: friendsCount,    onTap: { tabState.switchTab(1) }),
    StatItem(label: "Blends",    value: groupsCount,     onTap: { tabState.switchTab(2) }),
])
```

This keeps `TabState` logic inside `ProfileView` (where it belongs) rather than
inside the shared component.

### Pattern 4: PosterGrid Interface Design

`PosterGrid` wraps the `LazyVGrid` with the project's standard three-column config
and horizontal padding. It accepts a generic content closure so `ProfileView` can
pass `NavigationLink`-wrapped tiles and `FriendProfileView` can do the same:

```swift
// Extracted to Views/Shared/PosterGrid.swift
struct PosterGrid<Content: View>: View {
    @ViewBuilder let content: () -> Content

    private let columns = [
        GridItem(.flexible(), spacing: 8),
        GridItem(.flexible(), spacing: 8),
        GridItem(.flexible(), spacing: 8),
    ]

    var body: some View {
        LazyVGrid(columns: columns, spacing: 8) {
            content()
        }
        .padding(.horizontal, 24)
    }
}
```

Usage in ProfileView becomes:

```swift
PosterGrid {
    ForEach(watchedMovies) { movie in
        NavigationLink { MovieDetailView(tmdbId: movie.tmdbId, title: movie.title) } label: {
            PosterTile(posterPath: movie.posterPath, rating: movie.rating)
        }
        .buttonStyle(.plain)
    }
}
```

### Anti-Patterns to Avoid

- **Injecting environment objects into shared components:** `StatsRow` must not take
  `@Environment(TabState.self)`. Navigation callbacks belong in the parent view.
- **Combining all three into one file:** Each component gets its own file to match
  the existing `Views/Shared/` pattern.
- **Changing visual output:** This is a refactor. Any pixel-level difference in
  `ProfileView` is a regression. Do not adjust spacing, colours, or font sizes.
- **`AnyView` overuse:** `AnyView` is used above only as a workaround for the
  conditional tappable/non-tappable statCell return. An alternative is a dedicated
  `StatCell` sub-view — either is acceptable; avoid wrapping entire high-level views.
- **Returning a computed variable then immediately using it** (`swiftformat
  redundantProperty` rule): return expressions directly.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Remote image loading | Custom image cache | `AsyncImage` (built-in) | Already used throughout the project; zero-dep constraint |
| Three-column grid layout | Custom grid math | `LazyVGrid` with `GridItem(.flexible())` | Already the pattern in `ProfileView` |
| Rating formatting | Custom string builder | `String(format:)` with truncatingRemainder check | Already in `posterTile` — copy exactly |

**Key insight:** All three components already exist as private implementations.
The work is mechanical promotion to public structs, not invention.

---

## Common Pitfalls

### Pitfall 1: Breaking ProfileView visually
**What goes wrong:** Spacing, padding, or font sizes silently change because the
extracted struct uses slightly different default values.
**Why it happens:** Copying code while adjusting parameter names introduces subtle
differences.
**How to avoid:** Copy the implementation verbatim from `ProfileView.swift` into the
new struct body, then adjust only the interface (property names). Do a side-by-side
simulator comparison before and after.
**Warning signs:** Any visual diff in the Xcode canvas preview or simulator run.

### Pitfall 2: swiftlint type_body_length violation
**What goes wrong:** `StatsRow` with nested helper views may trigger the 300-line
warning on swiftlint's `type_body_length` rule.
**Why it happens:** The view's body plus private helpers can grow large.
**How to avoid:** Keep each component file lean. Extract `StatCell` as a separate
private struct within the same file if the body gets long.
**Warning signs:** `pre-commit` fails with `type_body_length` error.

### Pitfall 3: swiftformat wraparguments on multi-arg initializers
**What goes wrong:** Long `StatItem(label: "Watched", value: watchedTotal, onTap: nil)`
initializer calls exceed 120 chars on one line.
**Why it happens:** `.wraparguments before-first` is enforced by swiftformat.
**How to avoid:** Format long call sites as multi-line from the start:
```swift
StatItem(
    label: "Watched",
    value: watchedTotal,
    onTap: nil
)
```
**Warning signs:** swiftformat rewrites lines on commit hook, causing unexpected diffs.

### Pitfall 4: Forgetting to add new files to Xcode target
**What goes wrong:** File compiles in Finder but Xcode reports "cannot find type
'PosterTile' in scope."
**Why it happens:** SwiftUI files must be added to the Xcode project's target
membership — not just dropped into the folder.
**How to avoid:** Use Xcode's "Add Files to blnd_ios" (or drag-and-drop into the
Xcode project navigator directly) so the `.xcodeproj` references the file.
**Warning signs:** Build error about missing type immediately after extraction.

### Pitfall 5: StatItem identity in ForEach
**What goes wrong:** Using `ForEach(items)` without an explicit `id:` parameter on
a struct that does not conform to `Identifiable` causes a compile error.
**Why it happens:** `StatItem` is a plain struct.
**How to avoid:** Use `ForEach(items.indices, id: \.self)` as shown in the pattern
above (same approach used in `CastSectionView.swift`).

---

## Code Examples

Verified from source inspection of this codebase (HIGH confidence).

### Rating badge — exact logic from ProfileView lines 272–287
```swift
// Source: ProfileView.swift lines 272–287 (copy verbatim into PosterTile)
if let rating {
    HStack(spacing: 2) {
        Image(systemName: "star.fill")
            .font(.system(size: 8))
        Text(rating.truncatingRemainder(dividingBy: 1) == 0
            ? String(format: "%.0f", rating)
            : String(format: "%.1f", rating))
            .font(.system(size: 10, weight: .bold))
    }
    .foregroundStyle(.white)
    .padding(.horizontal, 5)
    .padding(.vertical, 3)
    .background(.black.opacity(0.7))
    .clipShape(Capsule())
    .padding(4)
}
```

### Poster placeholder — exact from ProfileView lines 261–264
```swift
// Source: ProfileView.swift lines 261–264
RoundedRectangle(cornerRadius: 8)
    .fill(AppTheme.posterGradient)
    .aspectRatio(2 / 3, contentMode: .fill)
```

### TMDB image URL base — w342 quality (from ProfileView line 253)
```swift
// Source: ProfileView.swift line 253
URL(string: "https://image.tmdb.org/t/p/w342\(path)")
// Note: MovieCard.swift uses w300 — ProfileView uses w342.
// PosterTile should use w342 to match ProfileView behaviour exactly.
```

### Three-column grid config — exact from ProfileView lines 26–29
```swift
// Source: ProfileView.swift lines 26–29
let posterColumns = [
    GridItem(.flexible(), spacing: 8),
    GridItem(.flexible(), spacing: 8),
    GridItem(.flexible(), spacing: 8),
]
```

### Preview pattern — matches AvatarView.swift
```swift
#Preview {
    PosterTile(posterPath: nil, rating: 4.5)
        .frame(width: 120)
        .padding()
        .background(AppTheme.background)
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@ObservableObject` + `@Published` | `@Observable` macro (iOS 17) | Swift 5.9 / iOS 17 | Simpler, less boilerplate |
| `ObservableObject` environment injection | `.environment(MyObject())` with `@Observable` | iOS 17 | Direct object injection, no wrapper |

**Relevant to this phase:** None of the three extracted components own state, so
neither `@Observable` nor `@State` applies inside them. Data flows in as `let`
properties only.

**Deprecated/outdated:**
- `ObservableObject` / `@Published`: not used in this project; do not introduce.
- `@EnvironmentObject`: superseded by `@Observable` + `.environment()` in iOS 17.

---

## Open Questions

1. **StatItem tappability — `AnyView` vs separate StatCell view**
   - What we know: Both approaches compile and pass linter. `AnyView` erases type
     identity (minor performance cost). A separate private `StatCell` struct keeps
     types concrete.
   - What's unclear: Project has no strong precedent for this exact pattern.
   - Recommendation: Use a private `StatCell: View` struct inside `StatsRow.swift`
     to avoid `AnyView`. This is cleaner and avoids swiftlint issues.

2. **StatsRow item order / labels for FriendProfileView**
   - What we know: Phase 8 only extracts for ProfileView parity. FriendProfileView
     usage is Phase 9.
   - What's unclear: FriendProfileView will show watched count, friends count,
     blends count — no watchlist. The `StatsRow` interface uses `[StatItem]`, so
     callers control which items appear. This is already handled by the design above.
   - Recommendation: No change needed — the `[StatItem]` array design handles
     variable-length stats rows naturally.

---

## Validation Architecture

> `workflow.nyquist_validation` is absent from `.planning/config.json` — treated as enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Swift Testing (`@Test`, `import Testing`) — detected in `blnd_iosTests.swift` |
| Config file | Xcode test target `blnd_iosTests` — no separate config file |
| Quick run command | Cmd+U in Xcode, or `xcodebuild test -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16'` |
| Full suite command | Same — single test file with one empty test |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| IOS-06 | `PosterTile` compiles and renders identically in `ProfileView` | manual (visual) | Xcode simulator run | N/A — visual parity test |
| IOS-06 | `StatsRow` compiles and renders identically in `ProfileView` | manual (visual) | Xcode simulator run | N/A — visual parity test |
| IOS-06 | `PosterGrid` compiles and renders identically in `ProfileView` | manual (visual) | Xcode simulator run | N/A — visual parity test |
| IOS-06 | New structs are importable by any view (compile-time) | compile | `xcodebuild build -scheme blnd_ios` | ❌ Wave 0 — new files |

### Sampling Rate

- **Per task commit:** Xcode build succeeds with zero errors/warnings + visual check in simulator
- **Per wave merge:** Full simulator run of ProfileView, confirming visual parity
- **Phase gate:** ProfileView indistinguishable from pre-refactor; PosterTile/StatsRow/PosterGrid exist in `Views/Shared/` and build cleanly before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `Views/Shared/PosterTile.swift` — IOS-06 (new file, Wave 1)
- [ ] `Views/Shared/StatsRow.swift` — IOS-06 (new file, Wave 1)
- [ ] `Views/Shared/PosterGrid.swift` — IOS-06 (new file, Wave 1)

*(No new test infrastructure required — visual parity via simulator is the verification method for all three components.)*

---

## Sources

### Primary (HIGH confidence)
- Direct source inspection: `blnd_ios/blnd_ios/Views/Profile/ProfileView.swift` — full `posterTile`, `statsRow`, `statItem`, `watchedGrid`, `watchlistGrid` implementations (lines 118–290)
- Direct source inspection: `blnd_ios/blnd_ios/Views/Shared/MovieCard.swift` — canonical shared component pattern
- Direct source inspection: `blnd_ios/blnd_ios/Views/Shared/AvatarView.swift` — canonical shared component pattern with optional data
- Direct source inspection: `blnd_ios/blnd_ios/Views/Friends/FriendProfileView.swift` — confirms component does not yet exist there
- Direct source inspection: `blnd_ios/.swiftformat`, `blnd_ios/.swiftlint.yml` — linting rules (maxwidth 120, wraparguments before-first, type_body_length 300)
- Direct source inspection: `blnd_ios/blnd_iosTests/blnd_iosTests.swift` — confirms test suite is a single empty test (no automated test coverage exists)
- iOS CLAUDE.md — confirms zero third-party dependencies, `@Observable`, `async/await`, `Views/Shared/` location for shared components

### Secondary (MEDIUM confidence)
- None required — all findings from primary source inspection.

### Tertiary (LOW confidence)
- None.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — project conventions inspected directly from source
- Architecture: HIGH — all three component interfaces derived directly from existing `ProfileView` private implementations
- Pitfalls: HIGH — derived from linter configs and direct codebase patterns (e.g. `CastSectionView` `ForEach(indices:)` pattern)

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (stable SwiftUI/iOS 17 APIs; project conventions unlikely to change)
