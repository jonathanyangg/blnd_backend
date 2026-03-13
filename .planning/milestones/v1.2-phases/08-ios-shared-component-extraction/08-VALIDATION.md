---
phase: 8
slug: ios-shared-component-extraction
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-12
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Swift Testing (`@Test`, `import Testing`) + Xcode build |
| **Config file** | Xcode test target `blnd_iosTests` |
| **Quick run command** | `xcodebuild build -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16'` |
| **Full suite command** | `xcodebuild test -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16'` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Xcode build succeeds with zero errors
- **After every plan wave:** Full simulator run of ProfileView, confirming visual parity
- **Before `/gsd:verify-work`:** ProfileView indistinguishable from pre-refactor
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 1 | IOS-06 | compile | `xcodebuild build -scheme blnd_ios` | ❌ W0 | ⬜ pending |
| 08-01-02 | 01 | 1 | IOS-06 | visual | Xcode simulator run | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Views/Shared/PosterTile.swift` — new file (Wave 1)
- [ ] `Views/Shared/StatsRow.swift` — new file (Wave 1)
- [ ] `Views/Shared/PosterGrid.swift` — new file (Wave 1)

*No new test infrastructure required — visual parity via simulator is the verification method.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| PosterTile renders identically to pre-refactor | IOS-06 | Visual parity — no pixel-level automated test | Run in simulator, compare ProfileView appearance |
| StatsRow renders identically to pre-refactor | IOS-06 | Visual parity | Run in simulator, compare ProfileView stats row |
| PosterGrid renders identically to pre-refactor | IOS-06 | Visual parity | Run in simulator, compare ProfileView poster grid |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
