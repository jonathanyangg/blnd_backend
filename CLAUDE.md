# BLND Backend

## Tech Stack
- **Framework**: FastAPI
- **ORM**: SQLAlchemy (models + queries)
- **Migrations**: Supabase CLI (`supabase migration new`, `supabase db push`)
- **Database**: Supabase Postgres + pgvector
- **Auth**: Supabase Auth via supabase-py (JWT) — only use of supabase-py
- **APIs**: TMDB (movie data), OpenAI (embeddings)
- **Linting**: pre-commit hooks with ruff, codespell, pyright

## Project Structure (Domain-Driven Design)
Each domain folder (`app/auth/`, `app/movies/`, etc.) contains:
- `models.py` — SQLAlchemy models
- `schemas.py` — Pydantic request/response models
- `services.py` — Business logic + SQLAlchemy queries
- `views.py` — FastAPI router endpoints
- `workflows.py` + `flows.py` — Multi-step orchestration (only in import_data, recommendations, groups)

## Commands
- **Dev server**: `uvicorn main:app --reload`
- **New migration**: `supabase migration new <name>`
- **Push migrations**: `supabase db push`
- **Install deps**: `pip install -r requirements.txt`
- **Lint**: `pre-commit run --all-files`

## Conventions
- Env vars loaded from `.env` via pydantic-settings (defaults to `""` for pyright compatibility)
- DB queries go through SQLAlchemy ORM (connected to Supabase Postgres via `DATABASE_URL`)
- supabase-py is used ONLY for Auth (signup, login, verify JWT)
- Async HTTP calls use httpx
- Movie embeddings: OpenAI text-embedding-3-small (1536 dims) stored in pgvector
- Supabase SDK returns optional types — always null-check `.user` and `.session` before access
- Use `datetime.now(timezone.utc)` not `datetime.utcnow()` (deprecated)

## Current Status

### Done
- Project scaffolding: folder structure, config, database, dependencies, main.py
- Pre-commit hooks: ruff, ruff-format, codespell, pyright
- Auth domain: models (SQLAlchemy Profile), schemas, services (Supabase Auth + SQLAlchemy), views
- Movies domain: models, schemas, views (stubbed)
- All domain routers registered in main.py with stub endpoints
- FastAPI server runs clean on `uvicorn main:app --reload`

### Next Steps
- [ ] Set up Supabase project + fill `.env`
- [ ] Install Supabase CLI + init project (`supabase init`, `supabase link`)
- [ ] Create initial migration (profiles, movies, watched_movies, friendships, groups, group_members, movie_embeddings)
- [ ] Enable pgvector + create match_movies RPC
- [ ] Build movies domain: TMDB search + caching via SQLAlchemy
- [ ] Build tracking domain: watch/rate/review CRUD
- [ ] Build import_data domain: Letterboxd CSV parser + workflow/flow
- [ ] Build recommendations domain: embeddings + taste vectors + similarity search
- [ ] Build friends domain: request/accept/reject/list
- [ ] Build groups domain: CRUD + group recommendations

---
*Last updated: 2026-03-02*
