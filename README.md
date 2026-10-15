# blnd Backend

Movie tracking app with AI-powered recommendations and social features. Like Letterboxd, but with personalized and group recommendations.

## Tech Stack
FastAPI / SQLAlchemy / Supabase (Postgres + pgvector + Auth) / TMDB API / OpenAI

## Setup

```bash
# Install Python and all locked dependencies
uv sync --all-groups

# Copy env template and fill in your keys
cp .env.example .env

# Run pgvector setup in Supabase SQL editor
# See sql/pgvector_setup.sql

# Run migrations
supabase db reset --local

# Or Postgres only, on the same port the tests use (127.0.0.1:54322):
docker compose up -d db

# Start dev server
uv run uvicorn main:app --reload
```

Run the test suite with `make test` or `uv run pytest`.

For Render, use `uv sync --locked --no-dev` as the build command and
`uv run --locked --no-dev uvicorn main:app --host 0.0.0.0 --port $PORT` as the start command.

## Project Structure
```
app/
├── auth/            # Signup, login, profiles
├── movies/          # TMDB search, movie details
├── tracking/        # Watch history, ratings, reviews
├── import_data/     # Letterboxd CSV import
├── recommendations/ # AI-powered recommendations
├── friends/         # Friend requests, friend lists
└── groups/          # Watch groups, group recommendations
```

## Environment Variables
See `.env.example` for required variables.
