alter table movies add column director text;
alter table movies add column "cast" jsonb default '[]';
alter table movies add column tagline text;
alter table movies add column backdrop_path text;
alter table movies add column imdb_id text;
