-- Smoke-test catalog for GET /recommendations/now.
-- Keep vote_count at or below 100000 so pytest can outrank these rows.

create or replace function dev_now_vec(spec jsonb)
returns vector
language plpgsql
as $$
declare
  parts text[] := '{}';
  i int;
begin
  for i in 0..1535 loop
    parts := parts || coalesce(spec ->> i::text, '0');
  end loop;
  return ('[' || array_to_string(parts, ',') || ']')::vector;
end;
$$;

insert into auth.users (id, instance_id, aud, role, email, created_at, updated_at)
values
  (
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    '00000000-0000-0000-0000-000000000000',
    'authenticated',
    'authenticated',
    'now-fan@test.local',
    now(),
    now()
  ),
  (
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    '00000000-0000-0000-0000-000000000000',
    'authenticated',
    'authenticated',
    'now-cold@test.local',
    now(),
    now()
  );

insert into movies (
  tmdb_id, title, year, overview, poster_path, genres, runtime, vote_average, vote_count, director
)
values
  (
    900001, 'Inception', 2010, 'A thief enters dreams.', '/inception.jpg',
    '[{"id": 878, "name": "Science Fiction"}]'::jsonb, 148, 8.4, 1000, 'Christopher Nolan'
  ),
  (
    900002, 'Dune', 2021, 'A desert planet decides a war.', '/dune.jpg',
    '[{"id": 878, "name": "Science Fiction"}]'::jsonb, 155, 8.0, 800, 'Denis Villeneuve'
  ),
  (
    900003, 'Arrival', 2016, 'A linguist learns an alien language.', '/arrival.jpg',
    '[{"id": 878, "name": "Science Fiction"}]'::jsonb, 116, 7.6, 700, 'Denis Villeneuve'
  ),
  (
    900010, 'The Godfather', 1972, 'A crime family changes hands.', '/godfather.jpg',
    '[{"id": 18, "name": "Drama"}]'::jsonb, 175, 9.2, 50000, 'Francis Ford Coppola'
  ),
  (
    900011, 'Parasite', 2019, 'A family takes jobs in a wealthy house.', '/parasite.jpg',
    '[{"id": 18, "name": "Drama"}]'::jsonb, 132, 8.5, 20000, 'Bong Joon Ho'
  );

insert into movie_embeddings (tmdb_id, embedding)
values
  (900001, dev_now_vec('{"0": "1"}'::jsonb)),
  (900002, dev_now_vec('{"0": "1", "1": "0.15"}'::jsonb)),
  (900003, dev_now_vec('{"0": "1", "2": "1.2"}'::jsonb)),
  (900010, dev_now_vec('{"3": "1"}'::jsonb)),
  (900011, dev_now_vec('{"4": "1"}'::jsonb));

insert into profiles (id, username, favorite_genres, taste_embedding)
values (
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  'now_fan',
  '["Science Fiction"]'::jsonb,
  dev_now_vec('{"0": "1"}'::jsonb)
);

insert into profiles (id, username)
values ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'now_cold');

insert into watched_movies (user_id, tmdb_id, rating)
values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 900001, 5);

drop function dev_now_vec(jsonb);

-- lists=1 is exact enough for this small local table. Production migrations keep lists=100.
do $$
declare
  idx name;
begin
  for idx in
    select i.relname
    from pg_class t
    join pg_index ix on t.oid = ix.indrelid
    join pg_class i on i.oid = ix.indexrelid
    join pg_am am on i.relam = am.oid
    where t.relname = 'movie_embeddings' and am.amname = 'ivfflat'
  loop
    execute format('drop index %I', idx);
  end loop;
end $$;

create index movie_embeddings_embedding_idx
  on movie_embeddings
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 1);
