# TV show support (backend v1)

## Scope

This PR adds a self-contained backend slice for show-level TV tracking behind
`TV_SUPPORT_ENABLED`, which defaults to `false`. It intentionally does not alter
movie recommendations, embeddings, comments, streaming availability, or any
existing `tmdb_id`-based movie pipeline.

## Acceptance criteria

| Criterion | Evidence | Status |
|---|---|---|
| TV support is disabled by default | `test_tv_support_defaults_off` | PROVEN locally for the configured settings object |
| TV search is unavailable while disabled | `test_tv_search_is_disabled_by_default` | PROVEN for the `/tv/search` endpoint |
| Enabled TV search calls mocked TMDB `/search/tv` | `test_tv_search_uses_tmdb_tv_search` | PROVEN with mocked TMDB |
| A same-numeric TV and movie ID remain distinct when tracking TV | `test_track_tv_show_does_not_collide_with_movie_id` | PROVEN with mocked TMDB and the local schema |
| Local migration builds the isolated TV schema | `make test-reset ARGS="tests/test_tv_shows.py -q"` applied `20261012000000_tv_shows.sql`, then 4 focused tests passed | PROVEN locally |
| Production migration safety and rollback | Not tested in this PR | NOT_PROVEN |
| Live TMDB behavior | Not tested; external integration intentionally mocked | NOT_PROVEN |
| iOS UI behavior | Deferred to iOS PR | NOT_PROVEN |

## Commands

### Red

`OPENAI_API_KEY=test-only-local make test-reset ARGS="tests/test_tv_shows.py -q"` —
exit 2. Initial attempt failed collection because this worktree had no `.env`
and `app.dependencies` required an OpenAI API key at import time. A local-only
test key unblocked collection. Expected red: 3 failed (`Settings` had no
`tv_support_enabled`) and 1 passed (disabled route 404). Two intermediate reds
were fixture issues: movie-only TMDB fake and missing test profile.

### Green focused

`OPENAI_API_KEY=test-only-local make test-reset ARGS="tests/test_tv_shows.py -q"` —
exit 0, `4 passed in 0.56s`.

### Green broader

- `uv run ruff check .` — exit 0, all checks passed.
- `uv run pyright` — exit 0, 0 errors, 0 warnings, 0 informations.
- `OPENAI_API_KEY=test-only-local make test ARGS=-q` — exit 0,
  `150 passed in 1.03s`.

The OpenAI value is a test-only local string; no production credential or
external OpenAI request was used.

## Limitations

This initial record documents the test-first plan. Update each status after
running the focused test and broader repository verification.
