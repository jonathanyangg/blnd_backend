-- One-way follows, separate from friendships.
--
-- friendships is a mutual relationship: a row is a request until status
-- becomes 'accepted', and either person can be requester or addressee.
-- follows is not that. follower_id follows followee_id in one direction only.
-- Following someone does not create a friendship, and accepting a friend
-- request does not insert a follow. The two can exist alone or together.
--
-- user_blocks applies to both. Blocking deletes the friendship and any
-- follows in either direction (see block_user). There is no private-profile
-- flag on profiles; lists are visible to any signed-in user the owner has
-- not blocked.

CREATE TABLE IF NOT EXISTS follows (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    follower_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    followee_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (follower_id, followee_id),
    CONSTRAINT follows_no_self_follow CHECK (follower_id <> followee_id)
);

-- List pages are ordered by id descending (append-only identity).
CREATE INDEX IF NOT EXISTS idx_follows_followee_id ON follows (followee_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_follows_follower_id ON follows (follower_id, id DESC);

-- Same pattern as friendships and user_blocks: RLS on, no policies.
-- The Data API (authenticated/anon) cannot read or write follows, so a
-- client cannot skip the API's block check. The API connects as a role
-- that bypasses RLS.
ALTER TABLE follows ENABLE ROW LEVEL SECURITY;

-- Push gate for the new_follower inbox event. Inbox is always written;
-- this column only skips the push when the recipient turns it off.
ALTER TABLE notification_preferences
    ADD COLUMN IF NOT EXISTS new_followers BOOLEAN NOT NULL DEFAULT true;
