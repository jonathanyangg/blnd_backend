# Feature: Letterboxd import persistence and watched CSV rating

Date: 2026-10-12 (extracted onto `feature/letterboxd-onboarding` from the 2026-10-05 work)
Repository: `blnd_backend`
Owner: Codex
Status: `PROVEN`

## Acceptance criteria

| ID | Criterion | Test or evidence | Status |
| --- | --- | --- | --- |
| B-1 | A Letterboxd export ZIP parses watched, watchlist, and rating fields. | `test_letterboxd_export_parses_watched_watchlist_and_rating` | `PROVEN` |
| B-2 | The authenticated import endpoint persists watched and watchlist entries and returns a correct summary. | `test_letterboxd_import_creates_watched_and_watchlist_entries` | `PROVEN` |
| B-3 | The full backend verification suite remains green. | `make verify` | `PROVEN` |

## Red/green evidence

### Before implementation

```sh
uv run pytest -q tests/test_import_letterboxd.py::test_letterboxd_export_parses_watched_watchlist_and_rating
```

Result: `FAIL`
Expected failure reason: the watched CSV row contained `Rating=4.5`, but the parsed `FilmRecord.rating` was `None`.

### After implementation

```sh
uv run pytest -q tests/test_import_letterboxd.py::test_letterboxd_export_parses_watched_watchlist_and_rating
make verify ARGS='tests/test_import_letterboxd.py'
make verify
```

Results:

- Parser focused test: `PASS` (1 test)
- Focused backend verify: `PASS` (2 tests)
- Full backend verify: `PASS` (148 tests) on this branch

Re-run on the extracted branch (2026-10-12): the parser test failed red with
`assert None == 4.5` before the `workflows.py` hunk was applied, then passed.
`make verify` ran with `OPENAI_API_KEY=test-key` (same dummy value as CI) and the
uncommitted local Makefile `verify` target (`make -f <main checkout>/Makefile verify`),
since `origin/main` has no `verify` target yet.

## Proof boundary

| Area | Status | Limitation |
| --- | --- | --- |
| CSV parsing | `PROVEN` | Fixture covers watched, rating, and watchlist fields |
| Local persistence | `PROVEN` | Local Supabase Postgres with mocked TMDB and transactional rollback |
| iOS upload | `PROVEN` | Covered by the iOS verification record |
| Live Letterboxd export | `NOT_PROVEN` | Intentionally excluded |
| Live TMDB matching | `NOT_PROVEN` | Intentionally mocked |
