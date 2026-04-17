CREATE TABLE notification_inbox (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    type TEXT NOT NULL,           -- 'friend_request', 'friend_accepted', 'group_invite', 'group_watchlist', 'friend_activity'
    from_user_id UUID REFERENCES profiles(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    data JSONB DEFAULT '{}',     -- extra context: tmdb_id, group_id, etc.
    read BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_notification_inbox_user_id ON notification_inbox(user_id, created_at DESC);
CREATE INDEX idx_notification_inbox_unread ON notification_inbox(user_id) WHERE read = false;
