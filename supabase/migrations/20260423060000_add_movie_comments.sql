-- movie_comments: top-level comments and one-level replies on movies
CREATE TABLE movie_comments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tmdb_id INTEGER NOT NULL,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    parent_id BIGINT REFERENCES movie_comments(id) ON DELETE CASCADE,
    body TEXT NOT NULL CHECK (char_length(body) BETWEEN 1 AND 1000),
    is_edited BOOLEAN NOT NULL DEFAULT false,
    deleted BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_movie_comments_tmdb_id_created ON movie_comments(tmdb_id, created_at DESC);
CREATE INDEX idx_movie_comments_user_id ON movie_comments(user_id);
CREATE INDEX idx_movie_comments_parent_id ON movie_comments(parent_id);

-- comment_likes: one like per user per comment
CREATE TABLE comment_likes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    comment_id BIGINT NOT NULL REFERENCES movie_comments(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, comment_id)
);

CREATE INDEX idx_comment_likes_comment_id ON comment_likes(comment_id);

-- Add comment_replies preference toggle to existing notification_preferences table
ALTER TABLE notification_preferences ADD COLUMN comment_replies BOOLEAN NOT NULL DEFAULT true;
