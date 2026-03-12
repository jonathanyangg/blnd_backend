---
phase: 7
slug: backend-public-profile-endpoints
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-12
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.5 |
| **Config file** | `blnd_backend/pyproject.toml` (`testpaths = ["tests"]`, `asyncio_mode = "auto"`) |
| **Quick run command** | `cd blnd_backend && python -m pytest tests/test_auth_public_profile.py -x` |
| **Full suite command** | `cd blnd_backend && python -m pytest tests/ -x` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd blnd_backend && python -m pytest tests/test_auth_public_profile.py -x`
- **After every plan wave:** Run `cd blnd_backend && python -m pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | API-01 | unit | `pytest tests/test_auth_public_profile.py::test_get_public_profile_success -x` | ❌ W0 | ⬜ pending |
| 07-01-02 | 01 | 1 | API-04 | unit | `pytest tests/test_auth_public_profile.py::test_public_profile_403 -x` | ❌ W0 | ⬜ pending |
| 07-02-01 | 02 | 1 | API-02 | unit | `pytest tests/test_auth_public_profile.py::test_get_public_watched_success -x` | ❌ W0 | ⬜ pending |
| 07-02-02 | 02 | 1 | API-03 | unit | `pytest tests/test_auth_public_profile.py::test_get_public_friends_success -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `blnd_backend/tests/test_auth_public_profile.py` — stubs for API-01 through API-04 (happy path + 403 cases)
- [ ] Verify existing `conftest.py` fixtures (`mock_db`, `app_client`) cover new endpoints or extend as needed

*Existing test infrastructure (pytest, conftest.py fixtures) covers framework needs.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
