# Collaborative filtering controls

## Acceptance criteria

| Criterion | Status | Evidence |
| --- | --- | --- |
| `CF_ENABLED=false` bypasses CF and restores embedding fallback | `PROVEN` | Focused red then green: 4 expected failures (`cf_enabled` missing), then 18 passed; later full suite 167 passed. |
| `CF_BLEND_WEIGHT` blends CF with embedding similarity and default preserves PR #5 behavior | `PROVEN` | Focused red then green: expected missing-attribute failure, then weight 0.5 produced the asserted blended match score; default 1.0 kept the pre-existing CF tests green. |
| Neighbour fan-out is capped | `PROVEN` | Focused red then green: expected missing-constant failure, then `MAX_NEIGHBOURS=1` with four eligible neighbours yielded no CF score. |

## Verification evidence

1. Red: `make test ARGS="tests/test_collaborative.py tests/test_match_scores.py -q"` — 4 failed (missing controls), 14 passed, exit 2. Log: `.artifacts/verification/cf-controls-red.log`.
2. Green focused: same command — 18 passed, exit 0. Log: `.artifacts/verification/cf-controls-green.log`.
3. Repository validation: `uvx ruff@0.11.2 check && uvx ruff@0.11.2 format --check && OPENAI_API_KEY=test-key make test ARGS="-q" && uv run pyright` in tmux session `cf-followup-validate` — Ruff clean, 167 passed, Pyright 0 errors/0 warnings, exit 0. Log: `.artifacts/verification/cf-controls-full.log`.

### Deviation

The tracked PR #5 head does not contain a `make verify` target (that script/target exists only as an uncommitted local change outside this worktree). The equivalent tracked checks from GitHub Actions plus Ruff and Pyright were run explicitly.

## How to flip the kill switch

Set either variable in the process environment or in `.env`, then restart the API. Pydantic Settings reads `CF_ENABLED` and `CF_BLEND_WEIGHT` (names are case-insensitive). `false`, `0`, and `no` turn the switch off.

| Variable | Default | Effect |
| --- | --- | --- |
| `CF_ENABLED` | `true` | `false` skips collaborative filtering. Ranking and match scores use embedding similarity. |
| `CF_BLEND_WEIGHT` | `1.0` | Share of the similarity term taken from CF when a movie also has an embedding. `1` keeps the CF score, `0` keeps the embedding, `0.5` splits them. |

Example, embeddings only:

```bash
CF_ENABLED=false uv run uvicorn main:app --reload
```

Example, half and half, without disabling CF:

```bash
CF_ENABLED=true CF_BLEND_WEIGHT=0.5 uv run uvicorn main:app --reload
```

## Boundaries

- Real-world neighbour data volumes and query performance are not load-tested.
- No external services, migrations, production data, or App Store behavior are involved.
