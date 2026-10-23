# Dev environment

Separate from prod. Prod is Supabase `wtnbecnjsougjjcplhqf` + Render `blnd_backend`. Never link the CLI to it from here.

| Piece | Dev |
|---|---|
| Supabase | `test_blnd_backend` (`ikdbhiozrtetognqcxbp`, West US). Paused projects must be restored in the dashboard first. |
| Render | `blnd-backend-dev` from branch `dev`, auto-deploy on every commit. Defined in `render.yaml`. |
| URL | https://blnd-backend-dev.onrender.com |

## One-time setup
1. Restore the dev Supabase project (Dashboard -> project -> Restore).
2. Migrations: `supabase link --project-ref ikdbhiozrtetognqcxbp && supabase db push` (check `supabase/.temp/project-ref` first).
3. Render -> New -> Blueprint -> this repo, branch `dev`. Fill the `sync: false` values (dev Supabase URL/keys, pooler `DATABASE_URL`, TMDB, OpenAI). `CONTACT_HASH_KEY` is generated.
4. Seed (runs on the service, uses its env): `render ssh blnd-backend-dev` then `uv run python scripts/seed_dev.py`, or a Render one-off job with that command.

Demo logins: `demo_casey|demo_alex|demo_sam|demo_maya` as `<username>@blnd.dev` / `Demo1234!` (premium, all friends).
The seed script refuses to run unless `SUPABASE_URL` is the dev project.

## After that
Merging to `dev` redeploys dev. Push new migrations with `supabase db push` while linked to the dev ref.
