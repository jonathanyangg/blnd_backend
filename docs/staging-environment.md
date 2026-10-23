# Staging environment

Separate from prod. Prod = Supabase `wtnbecnjsougjjcplhqf` + Render `blnd_backend`. Never link the CLI to prod from this setup.

| Piece | Staging |
|---|---|
| Supabase | `blnd_staging` (`dscyhvcajteutrzoatvf`, East US, Free plan) |
| Render | `blnd-backend-staging`, branch `dev`, auto-deploy on commit (`render.yaml`) |
| URL | https://blnd-backend-staging.onrender.com |
| iOS | `Staging` build configuration / `blnd_ios Staging` scheme (Release-based, for device and TestFlight) |

Local Docker Supabase + Maestro stay the main dev loop.

## Setup
1. Migrations: `supabase link --project-ref dscyhvcajteutrzoatvf && supabase db push` (check `supabase/.temp/project-ref` first).
2. Render -> New -> Blueprint -> this repo, branch `dev`. Fill the `sync: false` values (staging Supabase URL/keys, pooler `DATABASE_URL`, TMDB, OpenAI). `CONTACT_HASH_KEY` is generated.
3. Seed once, on the service (uses its env): `render ssh blnd-backend-staging`, then `uv run python scripts/seed_staging.py`.

Demo logins: `demo_casey|demo_alex|demo_sam|demo_maya` as `<username>@blnd.dev` / `Demo1234!` (premium, all friends).
The seed script refuses to run unless `SUPABASE_URL` is the staging project.

Merging to `dev` redeploys staging. Push new migrations with `supabase db push` while linked to the staging ref.
