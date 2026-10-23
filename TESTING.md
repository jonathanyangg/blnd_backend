# Testing at blnd

Status: layers 1-2 and the QA scripts below are implemented. Sections 3-4 are still proposals.
The iOS half (warm sims, Maestro flows, mini papers, PR gate) lives in `blnd_ios/TESTING.md`.

## Layers (measured on dev 8defb27, PR #45 included)
| Layer | Tool | Count | Result | Certainty |
|---|---|---|---|---|
| Backend unit/integration | pytest, in-process ASGI TestClient, isolated local Postgres `blnd_test`, rollback fixtures | 483 | 483 pass, 0 fail, 0 skip, same on every run | CERTAIN (no network, no skips) |
| API contract | Schemathesis vs `/openapi.json` | 117 | 117 pass, stable across 3 runs | CERTAIN for shape; cases are generated, so a new run can find a new edge case |

Run both exactly like CI does, without touching the demo data the warm sims use:

    scripts/qa/test.sh          # unit + contract  (also: test.sh unit | test.sh contract)

`scripts/qa/test.sh` rebuilds `blnd_test` from the `postgres` schema every run (any `supabase db reset` drops it),
sets `TEST_DATABASE_URL` and refuses to run if a `.env` exists in the repo. JUnit goes to `~/cursor-work/qa/reports/`.
Plain CI command stays `supabase start && supabase db reset --local --no-seed && uv run pytest -q`.

## Local backend for simulators
`scripts/qa/serve-local.sh` serves the local-Supabase backend on :8100 (rate limits off). `blnd_ios/tools/qa/warm.sh up` starts it.
Seeded demo users (supabase/seed.sql, local only): maya@blnd.local and leo@blnd.local (blnd+, friends), sam@blnd.local (free). Password `Premium123!`.
The feed still calls live TMDB, so UI tests that open the feed need internet.

## Merge automation
- `.github/workflows/automerge.yml`: a PR into `dev` labelled `automerge` is squash-merged once the `pytest` check is green.
- `.github/workflows/promote.yml`: every push to `dev` opens (or reuses) a "Release: dev into main" PR. Needs the repo setting
  Settings > Actions > General > "Allow GitHub Actions to create and approve pull requests".
- Nothing merges to `main` automatically: Jonathan merges the release PR.

## 3. Generate the Swift API client from OpenAPI (proposal)
Problem: iOS hand-writes request/response models, so contract drift ships (Blend cap 4 vs 8, the error envelope, is_premium).

Plan:
1. Backend CI exports the schema: `uv run python -c "import json; from main import app; print(json.dumps(app.openapi()))" > openapi.json` and commits it (or uploads it as an artifact). A CI check fails if it is stale.
2. Tighten the schema first: `response_model` on every route, explicit error responses (`{error:{code,message,request_id}, detail}`), stable `operationId`s (`generate_unique_id_function` = route name).
3. iOS adopts Apple's `swift-openapi-generator` (SPM build plugin, `URLSession` transport). Generated `Client` + `Components.Schemas` live in a `BlndAPI` package; existing `*API.swift` wrappers call into it, migrated one feature at a time.
4. A blnd_ios CI job pulls `openapi.json` from backend `dev` and builds; a breaking backend change fails the iOS build instead of the app at runtime.
Estimate: 1-2 days for the pipeline plus one feature migrated; the rest incrementally.

## 4. TestFlight internal build per `dev` update (proposal)
Goal: every merge to `blnd_ios/dev` lands on Jonathan's phone within ~30 min, with no App Review (internal testers only). This covers what the simulator can't: Sign in with Apple, Contacts, push, StoreKit sandbox.

Plan:
1. App Store Connect API key (issuer id, key id, .p8) stored as GitHub Actions secrets. Never in the repo.
2. fastlane `beta` lane: `match` (or Xcode cloud signing) -> `increment_build_number` (CI run number) -> `build_app` (Release config, but `API_BASE_URL` pointed at a dev/staging backend once one exists; until then prod) -> `upload_to_testflight(distribute_external: false, groups: ["Internal"])`.
3. GitHub Actions on `push: branches: [dev]` using a macOS runner (or Xcode Cloud, 25 free hours/month, which avoids managing signing in CI).
4. Changelog from merge commit titles goes into "What to Test".
Gating: unit tests + Maestro smoke must pass before upload.
Open question: a staging backend (separate Render service + Supabase branch) so TestFlight dev builds don't hit prod data. Needs paid plans or a second free project.

## Later
- local-bot-harness runs Maestro on each dev build and posts screenshots to the PR.
- Per-PR backend previews once on paid Render/Supabase.
