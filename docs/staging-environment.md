# Staging environment

Separate from prod. Prod = Supabase `wtnbecnjsougjjcplhqf` + Render `blnd_backend`. Never link the CLI to prod from this setup.

| Piece | Staging |
|---|---|
| Supabase | `blnd_staging` (`dscyhvcajteutrzoatvf`, East US, Free plan) |
| Render | `blnd-backend-staging`, branch `dev`, auto-deploy on commit (`render.yaml`) |
| URL | https://blnd-backend-staging.onrender.com |
| iOS | `Staging` build configuration / `blnd_ios Staging` scheme (Release-based, device + TestFlight). Sets `API_BASE_URL` and `SUPABASE_PROJECT_URL` (avatar storage) |
| Web | Vercel Preview env `NEXT_PUBLIC_API_URL` = staging URL. Production env stays on prod |

Local Docker Supabase + Maestro stay the main dev loop. No per-PR environments, no Supabase branching, no Maestro Cloud.

## External services
Real read-only: TMDB (metadata + where-to-watch), OpenAI embeddings, RapidAPI. Off or test-only: APNS/push (no keys set), SMS/email (no keys), RevenueCat (sandbox + webhook secret only for staging), affiliate links (`AMAZON_AFFILIATE_ENABLED=false`).

## Setup state
1. Supabase `blnd_staging`: all migrations in `supabase/migrations` applied (`supabase link --project-ref dscyhvcajteutrzoatvf && supabase db push`). Avatars bucket: `supabase db query --linked -f scripts/staging_storage.sql`.
2. Render: New -> Web Service -> this repo, branch `dev`, Ohio, Starter (Free works, ~1 min cold start). Build `pip install uv && uv sync --locked --no-dev`, start `uv run --locked --no-dev uvicorn main:app --host 0.0.0.0 --port $PORT`, health check `/health`, auto-deploy on commit. Environment -> Add from .env (see `.env.example`; `CONTACT_HASH_KEY` is a fresh random value; `CORS_ORIGIN_REGEX` lets Vercel previews call it).
3. Seed once from a shell that has the staging env loaded: `set -a; . ~/blnd-staging.env; set +a; uv run python scripts/seed_staging.py`. It refuses to run unless `SUPABASE_URL` is the staging project.

Demo logins: `demo_casey|demo_alex|demo_sam|demo_maya` as `<username>@blnd.dev` / `Demo1234!` (premium, all friends).

Merging to `dev` redeploys staging. Push new migrations with `supabase db push` while linked to the staging ref.

## Destructive-migration rehearsal (2026-10-23, staging)
Re-ran `20261015130000_hash_phone_numbers.sql` and `20260907000000_prune_embeddings_halfvec.sql` on synthetic rows after reverting `movie_embeddings.embedding` to `vector(1536)`:
- Phones: raw E.164 profile phone cleared, 64-hex digest kept, null untouched. `user_contacts`: raw rows deleted, hashed row kept (3 -> 1).
- Embeddings: obscure + unreferenced movie pruned, obscure-but-watched and popular kept (3 -> 2). Column became `halfvec(1536)`, HNSW index built, `match_movies()` returns rows.
- Synthetic rows removed afterwards.
Do the same on a fresh staging reset before any prod run; take a prod backup first.
