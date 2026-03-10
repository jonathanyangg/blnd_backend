-- Add negative_embedding to profiles for negative taste signals
ALTER TABLE profiles ADD COLUMN negative_embedding vector(1536);

-- Create hidden_movies table for "Don't Show This" feature
CREATE TABLE hidden_movies (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    tmdb_id INTEGER NOT NULL REFERENCES movies(tmdb_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, tmdb_id)
);
CREATE INDEX idx_hidden_movies_user_id ON hidden_movies(user_id);
