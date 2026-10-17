# Testing at blnd (proposal)

Status: proposal. Items 1-2 exist (pytest + Schemathesis, Maestro in blnd_ios). Items 3-4 are not implemented yet.

## Layers today
| Layer | Tool | Where | Runs |
|---|---|---|---|
| Backend unit/integration | pytest on local Supabase Postgres (unseeded) | `tests/` | locally, GitHub Actions on every PR |
| API contract | Schemathesis against FastAPI's `/openapi.json` | `tests/contract/` | same job, `-m contract` |
| iOS unit | XCTest | `blnd_iosTests` | locally on the iPhone 17 Pro sim |
| iOS end-to-end | Maestro flows | `blnd_ios/.maestro/` | locally against `localhost:8000` |

Local backend tests: `supabase start && supabase db reset --local --no-seed && uv run pytest -q`.
`seed.sql` demo data collides with fixtures, so tests always run unseeded.
Run `supabase db reset --local` afterwards if you want the demo seed back.

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
