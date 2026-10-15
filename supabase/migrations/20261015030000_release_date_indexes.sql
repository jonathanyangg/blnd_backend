-- Local integration branch. Adds date columns and indexes so year filters
-- can use release_date (movies) and first_air_date (TV). Existing year
-- columns stay; queries fall back to them when the date is null.

alter table movies add column if not exists release_date date;
create index if not exists idx_movies_release_date on movies (release_date);

alter table tv_shows add column if not exists first_air_date date;
create index if not exists idx_tv_shows_first_air_date on tv_shows (first_air_date);
