create table watchlist_movies (
    id bigint generated always as identity primary key,
    user_id uuid not null references profiles(id) on delete cascade,
    tmdb_id int not null references movies(tmdb_id),
    added_date date,
    created_at timestamptz default now(),
    unique(user_id, tmdb_id)
);
