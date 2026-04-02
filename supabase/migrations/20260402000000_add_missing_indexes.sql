CREATE INDEX IF NOT EXISTS idx_hidden_movies_user_id ON hidden_movies(user_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_movies_tmdb_id ON watchlist_movies(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_friendships_requester_id ON friendships(requester_id);
