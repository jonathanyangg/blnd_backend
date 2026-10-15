-- iOS share_ratings is everyone | friends | off. The value stays in
-- notification_preferences.share_ratings_activity (the API name is share_ratings).
-- "blends" is no longer an audience; fold any local rows back to friends.

UPDATE notification_preferences
SET share_ratings_activity = 'friends'
WHERE share_ratings_activity = 'blends';

ALTER TABLE notification_preferences
    DROP CONSTRAINT notification_preferences_share_ratings_activity_check;

ALTER TABLE notification_preferences
    ADD CONSTRAINT notification_preferences_share_ratings_activity_check
    CHECK (share_ratings_activity IN ('everyone', 'friends', 'off'));
