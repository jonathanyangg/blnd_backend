-- Revised comment model:
--  * parent_id points to the DIRECT parent comment (root is resolved at read time),
--    so reply_to_user_id is redundant (= author of the direct parent) and is dropped.
--  * shorten body cap to 250 chars to inherently curb spam.
--  * add an independent comment_mentions notification toggle.
ALTER TABLE movie_comments DROP COLUMN IF EXISTS reply_to_user_id;

ALTER TABLE movie_comments DROP CONSTRAINT IF EXISTS movie_comments_body_check;
ALTER TABLE movie_comments ADD CONSTRAINT movie_comments_body_check
    CHECK (char_length(body) BETWEEN 1 AND 250);

ALTER TABLE notification_preferences
    ADD COLUMN comment_mentions BOOLEAN NOT NULL DEFAULT true;
