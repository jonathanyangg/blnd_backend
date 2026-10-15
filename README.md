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
├── friends/         # Friend requests, blocks, one-way follows
└── groups/          # Watch groups, group recommendations
```

## Environment Variables
See `.env.example` for required variables.

## Follows and friends

Friendships are mutual. `friendships` stores a request from `requester_id` to `addressee_id` until `status` is `accepted`. Either person is then the other's friend.

Follows are one-way and stored in `follows` (`follower_id`, `followee_id`). Following someone does not create a friendship, and accepting a friend request does not create a follow. A pair can have either, both, or neither. The unique pair rejects duplicates, and a check constraint rejects self-follows.

Blocks apply to both. Blocking someone deletes the friendship and any follows in either direction, and neither person can follow the other while the block stands. Profiles have no private flag, so follower and following lists are visible to any signed-in user the owner has not blocked. Counts on a profile are totals. A list hides anyone in a block with the viewer, so a page can be shorter than the count.
