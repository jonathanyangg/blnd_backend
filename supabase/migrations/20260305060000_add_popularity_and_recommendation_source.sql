-- Track where the user found this movie: 'manual', 'recommendation', 'letterboxd_import'
ALTER TABLE watched_movies ADD COLUMN source text DEFAULT 'manual';
ALTER TABLE watchlist_movies ADD COLUMN source text DEFAULT 'manual';
