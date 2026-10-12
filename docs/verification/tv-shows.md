# TV show support (backend v1)

## Scope

This PR adds a self-contained backend slice for show-level TV tracking behind
`TV_SUPPORT_ENABLED`, which defaults to `false`. It intentionally does not alter
movie recommendations, embeddings, comments, streaming availability, or any
existing `tmdb_id`-based movie pipeline.

## Acceptance criteria

| Criterion | Evidence | Status |
|---|---|---|
| TV support is disabled by default | `test_tv_support_defaults_off` | PARTIALLY_PROVEN |
| TV search is unavailable while disabled | `test_tv_search_is_disabled_by_default` | PARTIALLY_PROVEN |
| Enabled TV search calls mocked TMDB `/search/tv` | `test_tv_search_uses_tmdb_tv_search` | PARTIALLY_PROVEN |
| A same-numeric TV and movie ID remain distinct when tracking TV | `test_track_tv_show_does_not_collide_with_movie_id` | PARTIALLY_PROVEN |
| Local migration builds the isolated TV schema | focused integration test | PARTIALLY_PROVEN |
| Production migration safety and rollback | Not tested in this PR | NOT_PROVEN |
| Live TMDB behavior | Not tested; external integration intentionally mocked | NOT_PROVEN |
| iOS UI behavior | Deferred to iOS PR | NOT_PROVEN |

## Commands

- `make test-reset ARGS="tests/test_tv_shows.py -q"` — expected red before
  implementation because the new API and schema do not exist.

## Limitations

This initial record documents the test-first plan. Update each status after
running the focused test and broader repository verification.
