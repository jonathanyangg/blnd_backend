# Roadmap: BLND

## Milestones

- ✅ **v1.0 Letterboxd Import** — Phases 1-3 (shipped 2026-03-09)
- 🚧 **v1.1 Letterboxd Integration Frontend** — Phases 4-6 (in progress)

## Phases

<details>
<summary>✅ v1.0 Letterboxd Import (Phases 1-3) — SHIPPED 2026-03-09</summary>

- [x] Phase 1: Schema (2/2 plans) — completed 2026-03-04
- [x] Phase 2: Core Import Workflow (3/3 plans) — completed 2026-03-05
- [x] Phase 3: Polish and Hardening (1/1 plan) — completed 2026-03-05

See: `.planning/milestones/v1.0-ROADMAP.md` for full details.

</details>

### 🚧 v1.1 Letterboxd Integration Frontend (In Progress)

**Milestone Goal:** Users can trigger a Letterboxd import entirely within BLND — log in via in-app webview, capture the ZIP automatically, upload to backend, and see results — while taste profiles are rebuilt after every successful import.

#### Phase 4: Backend Taste Rebuild Hook

**Goal**: Backend triggers taste profile rebuild after every successful Letterboxd import
**Depends on**: Nothing (independent of iOS track)
**Requirements**: BKND-01
**Success Criteria** (what must be TRUE):
  1. After a successful `POST /import/letterboxd`, the user's taste profile is rebuilt without any additional API call
  2. The taste rebuild fires after the import response is returned to the client (non-blocking)
  3. A failed or zero-import result does not trigger an unnecessary rebuild
**Plans**: 1 plan

Plans:
- [x] 04-01-PLAN.md — Add BackgroundTasks rebuild hook to import_letterboxd endpoint (TDD)

#### Phase 5: iOS Webview Import Flow

**Goal**: User can reach the Letterboxd export page inside BLND and the app captures the ZIP download automatically
**Depends on**: Nothing (independent of Phase 4, parallel track)
**Requirements**: IMPT-01, IMPT-02, IMPT-03, IMPT-04
**Success Criteria** (what must be TRUE):
  1. User can tap "Import from Letterboxd" in Profile and an in-app screen appears
  2. A WKWebView loads Letterboxd's data export page without leaving the app
  3. User can log into their Letterboxd account inside the webview
  4. When user taps "Export Your Data" on Letterboxd, the app intercepts the ZIP download and the user never sees a Safari redirect or system download prompt
**Plans**: 2 plans

Plans:
- [x] 05-01-PLAN.md — WKWebView bridge with download interception + Letterboxd webview container
- [ ] 05-02-PLAN.md — Import button on ProfileView + context/instructions screen + flow wiring

#### Phase 6: iOS Upload and Results

**Goal**: After ZIP is captured, the app uploads it and shows the user what happened
**Depends on**: Phase 5
**Requirements**: IMPT-05, IMPT-06, IMPT-07, IMPT-08, IMPT-09
**Success Criteria** (what must be TRUE):
  1. After ZIP capture, upload to the backend begins automatically with no user action required
  2. User sees a loading indicator while the import is processing
  3. User sees imported, skipped, and failed counts when the import completes
  4. User can tap Done to return to Profile after viewing results
  5. If the import fails, user sees an error message and can retry without leaving the screen
**Plans**: TBD

## Phase Details

### Phase 4: Backend Taste Rebuild Hook
**Goal**: Backend triggers taste profile rebuild after every successful Letterboxd import
**Depends on**: Nothing (first phase of v1.1, independent of iOS)
**Requirements**: BKND-01
**Success Criteria** (what must be TRUE):
  1. After a successful `POST /import/letterboxd`, the user's taste profile is rebuilt without any additional API call
  2. The taste rebuild fires after the import response is returned to the client (non-blocking)
  3. A failed or zero-import result does not trigger an unnecessary rebuild
**Plans**: 1 plan

Plans:
- [x] 04-01-PLAN.md — Add BackgroundTasks rebuild hook to import_letterboxd endpoint (TDD)

### Phase 5: iOS Webview Import Flow
**Goal**: User can reach the Letterboxd export page inside BLND and the app captures the ZIP download automatically
**Depends on**: Nothing (parallel to Phase 4)
**Requirements**: IMPT-01, IMPT-02, IMPT-03, IMPT-04
**Success Criteria** (what must be TRUE):
  1. User can tap "Import from Letterboxd" in Profile and an in-app screen appears
  2. A WKWebView loads Letterboxd's data export page without leaving the app
  3. User can log into their Letterboxd account inside the webview
  4. When user taps "Export Your Data" on Letterboxd, the app intercepts the ZIP download and the user never sees a Safari redirect or system download prompt
**Plans**: 2 plans

Plans:
- [x] 05-01-PLAN.md — WKWebView bridge with download interception + Letterboxd webview container
- [ ] 05-02-PLAN.md — Import button on ProfileView + context/instructions screen + flow wiring

### Phase 6: iOS Upload and Results
**Goal**: After ZIP is captured, the app uploads it and shows the user what happened
**Depends on**: Phase 5
**Requirements**: IMPT-05, IMPT-06, IMPT-07, IMPT-08, IMPT-09
**Success Criteria** (what must be TRUE):
  1. After ZIP capture, upload to the backend begins automatically with no user action required
  2. User sees a loading indicator while the import is processing
  3. User sees imported, skipped, and failed counts when the import completes
  4. User can tap Done to return to Profile after viewing results
  5. If the import fails, user sees an error message and can retry without leaving the screen
**Plans**: TBD

## Progress

**Execution Order:**
Phases 4 and 5 are independent (parallel tracks). Phase 6 depends on Phase 5. Recommended order: 4 → 5 → 6.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Schema | v1.0 | 2/2 | Complete | 2026-03-04 |
| 2. Core Import Workflow | v1.0 | 3/3 | Complete | 2026-03-05 |
| 3. Polish and Hardening | v1.0 | 1/1 | Complete | 2026-03-05 |
| 4. Backend Taste Rebuild Hook | v1.1 | 1/1 | Complete | 2026-03-10 |
| 5. iOS Webview Import Flow | v1.1 | 1/2 | In Progress | - |
| 6. iOS Upload and Results | v1.1 | 0/TBD | Not started | - |
