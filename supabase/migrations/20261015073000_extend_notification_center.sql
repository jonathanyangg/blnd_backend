-- Extend the existing notification inbox and preferences for the notification
-- center. No second notifications table: rows already fan out into
-- notification_inbox, and the API groups them at query time.
--
-- watched_with is a recognized inbox type for a feature that is not on main
-- yet. Nothing writes it. follow_request is the same shape as friend_request
-- (accept / decline) but there is no follows table, so those rows stay empty
-- unless something inserts one.

ALTER TABLE notification_inbox
    ADD COLUMN group_key TEXT;

CREATE INDEX idx_notification_inbox_user_group
    ON notification_inbox (user_id, group_key)
    WHERE group_key IS NOT NULL;

ALTER TABLE notification_preferences
    ADD COLUMN share_ratings_activity TEXT NOT NULL DEFAULT 'friends',
    ADD COLUMN friends_ratings_in_app BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN friends_ratings_push BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN blend_activity_in_app BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN blend_activity_push BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN comments_likes_in_app BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN comments_likes_push BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN watched_with_tags_in_app BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN watched_with_tags_push BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN recommendations_in_app BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN recommendations_push BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE notification_preferences
    ADD CONSTRAINT notification_preferences_share_ratings_activity_check
    CHECK (share_ratings_activity IN ('everyone', 'friends', 'blends', 'off'));

ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_inbox ENABLE ROW LEVEL SECURITY;

CREATE POLICY notification_preferences_owner_select
    ON notification_preferences FOR SELECT TO authenticated
    USING (user_id = auth.uid());

CREATE POLICY notification_preferences_owner_insert
    ON notification_preferences FOR INSERT TO authenticated
    WITH CHECK (user_id = auth.uid());

CREATE POLICY notification_preferences_owner_update
    ON notification_preferences FOR UPDATE TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

CREATE POLICY notification_preferences_owner_delete
    ON notification_preferences FOR DELETE TO authenticated
    USING (user_id = auth.uid());

CREATE POLICY notification_inbox_owner_select
    ON notification_inbox FOR SELECT TO authenticated
    USING (user_id = auth.uid());

CREATE POLICY notification_inbox_owner_update
    ON notification_inbox FOR UPDATE TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

GRANT SELECT, INSERT, UPDATE, DELETE ON notification_preferences TO authenticated;
GRANT SELECT, UPDATE ON notification_inbox TO authenticated;
