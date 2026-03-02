alter table profiles add column taste_bio text;
alter table profiles add column favorite_genres jsonb default '[]';
alter table profiles add column taste_embedding vector(1536);
