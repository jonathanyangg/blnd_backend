-- Instagram-style replies: replies-to-replies collapse to the root chain,
-- while reply_to_user_id records who was actually being replied to (for @mentions).
ALTER TABLE movie_comments ADD COLUMN reply_to_user_id UUID REFERENCES profiles(id) ON DELETE SET NULL;
