---
phase: 9
slug: friendprofileview-revamp
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-12
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | XCTest (project-included, no setup needed) |
| **Config file** | blnd_ios.xcodeproj (Xcode scheme) |
| **Quick run command** | `xcodebuild build -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16'` |
| **Full suite command** | `xcodebuild test -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16'` |
| **Estimated runtime** | ~30 seconds (build only) |

---

## Sampling Rate

- **After every task commit:** Run `xcodebuild build -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16' 2>&1 | tail -5`
- **After every plan wave:** Run build check + human simulator verification
- **Before `/gsd:verify-work`:** Build succeeds + human verifies all 5 success criteria in simulator
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 1 | IOS-01, IOS-02, IOS-03, IOS-04, IOS-05, IOS-07 | build | `xcodebuild build -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16' 2>&1 \| tail -5` | ✅ | ⬜ pending |
| 09-02-01 | 02 | 1 | IOS-01 | manual-only | Build check | ✅ | ⬜ pending |
| 09-02-02 | 02 | 1 | IOS-02, IOS-03 | manual-only | Build check | ✅ | ⬜ pending |
| 09-02-03 | 02 | 1 | IOS-04, IOS-05 | manual-only | Build check | ✅ | ⬜ pending |
| 09-02-04 | 02 | 1 | IOS-07 | manual-only | Build check | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. No automated unit tests added — SwiftUI view behavior requires simulator verification.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Stats row displays watched/friends/blends counts | IOS-01 | SwiftUI view rendering requires running simulator | Open friend profile, verify 3 stats show correct counts |
| 3-column poster grid with star ratings | IOS-02 | Visual layout verification | Scroll friend profile, verify grid renders with ratings |
| Tapping poster navigates to MovieDetailView | IOS-03 | Navigation requires simulator | Tap any poster, verify MovieDetailView loads |
| Tapping friends count opens bottom sheet | IOS-04 | Sheet presentation requires simulator | Tap friends count stat, verify sheet shows friends list |
| Tapping friend-of-friend pushes FriendProfileView | IOS-05 | Recursive navigation requires simulator | Tap a friend in sheet, verify sheet dismisses and new profile pushes |
| Loading indicator and empty state | IOS-07 | Timing-dependent UI state | Verify spinner shows during load, empty message for zero watched |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
