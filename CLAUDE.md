# BLND Backend

## Tech Stack
- **Framework**: FastAPI
- **ORM**: SQLAlchemy + Alembic (migrations)
- **Database**: Supabase Postgres + pgvector
- **Auth**: Supabase Auth (JWT)
- **APIs**: TMDB (movie data), OpenAI (embeddings)

## Project Structure (Domain-Driven Design)
Each domain folder (`app/auth/`, `app/movies/`, etc.) contains:
- `models.py` — SQLAlchemy models
- `schemas.py` — Pydantic request/response models
- `services.py` — Business logic
- `views.py` — FastAPI router endpoints
- `workflows.py` + `flows.py` — Multi-step orchestration (only in import_data, recommendations, groups)

## Commands
- **Dev server**: `uvicorn main:app --reload`
- **New migration**: `alembic revision --autogenerate -m "description"`
- **Run migrations**: `alembic upgrade head`
- **Install deps**: `pip install -r requirements.txt`

## Conventions
- Env vars loaded from `.env` via pydantic-settings
- All DB queries go through SQLAlchemy (Supabase client used only for Auth)
- Async HTTP calls use httpx
- Movie embeddings: OpenAI text-embedding-3-small (1536 dims) stored in pgvector
