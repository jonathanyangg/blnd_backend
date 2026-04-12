ALTER TABLE notification_preferences
    ADD COLUMN IF NOT EXISTS badge_count INTEGER NOT NULL DEFAULT 0;
