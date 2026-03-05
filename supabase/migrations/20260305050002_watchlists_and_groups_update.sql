-- 1. Create standalone watchlists table
CREATE TABLE watchlists (
    id bigint generated always as identity primary key,
    created_at timestamptz default now()
);

-- 2. Add watchlist_id to profiles
ALTER TABLE profiles ADD COLUMN watchlist_id bigint references watchlists(id);

-- 3. Add watchlist_id to groups
ALTER TABLE groups ADD COLUMN watchlist_id bigint references watchlists(id);

-- 4. Drop old watchlist_movies table (empty, safe to drop)
DROP TABLE watchlist_movies;

-- 5. Recreate watchlist_movies with watchlist_id FK
CREATE TABLE watchlist_movies (
    id bigint generated always as identity primary key,
    watchlist_id bigint not null references watchlists(id) on delete cascade,
    tmdb_id int not null references movies(tmdb_id),
    added_by uuid references profiles(id),
    added_date date,
    created_at timestamptz default now(),
    unique(watchlist_id, tmdb_id)
);

-- 6. Create a watchlist for each existing profile and link it
DO $$
DECLARE r record;
        wl_id bigint;
BEGIN
    FOR r IN SELECT id FROM profiles LOOP
        INSERT INTO watchlists DEFAULT VALUES RETURNING id INTO wl_id;
        UPDATE profiles SET watchlist_id = wl_id WHERE id = r.id;
    END LOOP;
END $$;
