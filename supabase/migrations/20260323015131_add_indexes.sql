-- Add indexes on frequently queried foreign key columns to prevent full table scans at scale

CREATE INDEX IF NOT EXISTS idx_watched_movies_user_id ON watched_movies(user_id);

CREATE INDEX IF NOT EXISTS idx_watchlist_movies_watchlist_id ON watchlist_movies(watchlist_id);

CREATE INDEX IF NOT EXISTS idx_friendships_addressee_id ON friendships(addressee_id);

CREATE INDEX IF NOT EXISTS idx_group_members_user_id ON group_members(user_id);
