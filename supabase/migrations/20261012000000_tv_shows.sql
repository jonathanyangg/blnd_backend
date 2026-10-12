-- Isolated, show-level TV support. This intentionally does not reuse
-- movie tmdb_id columns because TMDB movie and TV IDs overlap.
create table tv_shows (
    tmdb_id int primary key,
    title text not null,
    first_air_year int,
    overview text,
    poster_path text,
    backdrop_path text,
    genres jsonb default '[]',
    number_of_seasons int,
    episode_run_time int,
    vote_average float,
    vote_count int,
    cached_at timestamptz default now()
);

create table watched_tv_shows (
    id bigint generated always as identity primary key,
    user_id uuid not null references profiles(id) on delete cascade,
    tmdb_id int not null references tv_shows(tmdb_id),
    rating float check (rating >= 0.5 and rating <= 5.0),
    review text,
    watched_date date,
    source text not null default 'manual',
    created_at timestamptz default now(),
    unique(user_id, tmdb_id)
);
