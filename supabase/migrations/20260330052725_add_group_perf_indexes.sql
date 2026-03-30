-- Performance indexes for group queries

-- group_members lookups by group_id (used by list_groups batch, _group_detail, membership checks)
CREATE INDEX IF NOT EXISTS idx_group_members_group_id ON group_members(group_id);

-- Composite index for fast membership verification (_verify_membership)
CREATE INDEX IF NOT EXISTS idx_group_members_composite ON group_members(group_id, user_id);

-- watched_movies sorted by rating for taste embedding queries
CREATE INDEX IF NOT EXISTS idx_watched_movies_user_rating ON watched_movies(user_id, rating DESC NULLS LAST);
