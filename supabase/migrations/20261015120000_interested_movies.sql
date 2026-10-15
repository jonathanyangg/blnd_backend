-- Notes import can save a title as interested, which is not watched and
-- not on the watchlist. The iOS commit body sends this bucket by name.
CREATE TABLE interested_movies (
    id bigint generated always as identity primary key,
    user_id uuid not null references profiles(id) on delete cascade,
    tmdb_id int not null references movies(tmdb_id) on delete cascade,
    source text not null default 'manual',
    created_at timestamptz not null default now(),
    unique (user_id, tmdb_id)
);

CREATE INDEX idx_interested_movies_user_id ON interested_movies (user_id);
