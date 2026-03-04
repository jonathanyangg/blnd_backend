alter table profiles add column if not exists taste_bio text;
alter table profiles add column if not exists favorite_genres jsonb default '[]';
alter table profiles add column if not exists taste_embedding vector(1536);
