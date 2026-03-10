---
phase: 4
slug: backend-taste-rebuild-hook
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-09
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.5 + pytest-asyncio 0.25.3 |
| **Config file** | `blnd_backend/pyproject.toml` (`testpaths = ["tests"]`, `asyncio_mode = "auto"`) |
| **Quick run command** | `cd /Users/adamrose/Desktop/blnd/blnd_backend && pytest tests/ -x -q` |
| **Full suite command** | `cd /Users/adamrose/Desktop/blnd/blnd_backend && pytest tests/ -v` |
| **Estimated runtime** | ~2 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd /Users/adamrose/Desktop/blnd/blnd_backend && pytest tests/ -x -q`
- **After every plan wave:** Run `cd /Users/adamrose/Desktop/blnd/blnd_backend && pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 2 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 0 | BKND-01 | unit | `pytest tests/test_import_views.py -x -q` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | BKND-01 | unit | `pytest tests/test_import_views.py -x -q` | ❌ W0 | ⬜ pending |
| 04-01-03 | 01 | 1 | BKND-01 | unit | `pytest tests/test_import_views.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `blnd_backend/tests/` directory — does not exist; must be created
- [ ] `blnd_backend/tests/__init__.py` — empty init file
- [ ] `blnd_backend/tests/conftest.py` — shared fixtures: mock `db` session, mock `openai_client`, `rebuild_taste_profile` mock, `run_letterboxd_import` mock returning `ImportSummaryResponse`
- [ ] `blnd_backend/tests/test_import_views.py` — covers BKND-01: verify `add_task` called when `imported > 0`, not called when `imported == 0`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Rebuild fires post-response (non-blocking) | BKND-01 | Requires observing timing of background task relative to HTTP response | curl POST /import/letterboxd with a zip, check logs for rebuild line appearing after HTTP 200 is returned |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 2s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
