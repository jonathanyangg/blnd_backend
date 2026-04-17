CREATE TABLE liked_actors (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    tmdb_person_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    profile_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, tmdb_person_id)
);

CREATE INDEX idx_liked_actors_user_id ON liked_actors(user_id);
