-- watched_movies: friends-who-watched queries filter by tmdb_id across users
CREATE INDEX IF NOT EXISTS idx_watched_movies_tmdb_id ON watched_movies(tmdb_id);

-- movies: exploration pool query in recommendation pipeline
CREATE INDEX IF NOT EXISTS idx_movies_exploration_pool
    ON movies(vote_average DESC)
    WHERE vote_average >= 6.0 AND vote_count >= 50 AND runtime >= 45;

-- hidden_movies: JOIN on tmdb_id with movie_embeddings in taste computation
CREATE INDEX IF NOT EXISTS idx_hidden_movies_tmdb_id ON hidden_movies(tmdb_id);

-- watchlist_movies: account deletion UPDATEs by added_by
CREATE INDEX IF NOT EXISTS idx_watchlist_movies_added_by ON watchlist_movies(added_by);
