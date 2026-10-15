-- Swipe signals. Separate from watchlist_movies and from hidden_movies.
-- interested: positive taste, not a save. not_for_me: weak negative, not a hide.
-- Weights and item-item CF: docs/swipe-signals.md.
CREATE TABLE movie_interactions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    tmdb_id INTEGER NOT NULL REFERENCES movies(tmdb_id) ON DELETE CASCADE,
    interaction_type TEXT NOT NULL CHECK (interaction_type IN ('interested', 'not_for_me')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, tmdb_id)
);

-- Taste rebuild joins interactions to movie_embeddings on tmdb_id.
CREATE INDEX idx_movie_interactions_tmdb_id ON movie_interactions (tmdb_id);

ALTER TABLE movie_interactions ENABLE ROW LEVEL SECURITY;
