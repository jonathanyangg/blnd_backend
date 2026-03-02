# BLND Backend

Movie tracking app with AI-powered recommendations and social features. Like Letterboxd, but with personalized and group recommendations.

## Tech Stack
FastAPI / SQLAlchemy / Supabase (Postgres + pgvector + Auth) / TMDB API / OpenAI

## Setup

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy env template and fill in your keys
cp .env.example .env

# Run pgvector setup in Supabase SQL editor
# See sql/pgvector_setup.sql

# Run migrations
alembic upgrade head

# Start dev server
uvicorn main:app --reload
```

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
