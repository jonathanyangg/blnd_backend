-- People tagged on a movie watch log ("watched with").
-- owner_id is the watch-log owner, copied so SELECT policies do not have to
-- read watched_movies (that table has RLS and no SELECT policy).

CREATE TABLE watched_with (
    watched_movie_id bigint NOT NULL REFERENCES watched_movies(id) ON DELETE CASCADE,
    owner_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (watched_movie_id, user_id)
);

CREATE INDEX idx_watched_with_user_id ON watched_with (user_id);
CREATE INDEX idx_watched_with_owner_id ON watched_with (owner_id);

ALTER TABLE watched_with ENABLE ROW LEVEL SECURITY;

-- Owner and tagged companion can read. Writes go through the API (service role),
-- which bypasses RLS and enforces the friend / Blend check.
CREATE POLICY watched_with_select_owner_or_companion
    ON watched_with
    FOR SELECT
    TO authenticated
    USING (owner_id = auth.uid() OR user_id = auth.uid());

GRANT SELECT ON watched_with TO authenticated;
GRANT ALL ON watched_with TO service_role;
