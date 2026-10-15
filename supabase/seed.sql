-- Local demo for blnd+. Every account's password is Premium123!
-- `supabase db reset` loads this after migrations. Safe to re-run.

insert into auth.users (
    instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
    raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
    confirmation_token, email_change, email_change_token_new, recovery_token
) values
    (
        '00000000-0000-0000-0000-000000000000',
        '00000000-0000-4000-8000-0000000000a1',
        'authenticated', 'authenticated', 'maya@blnd.local',
        extensions.crypt('Premium123!', extensions.gen_salt('bf')),
        now(),
        '{"provider":"email","providers":["email"]}',
        '{"email":"maya@blnd.local"}',
        now(), now(), '', '', '', ''
    ),
    (
        '00000000-0000-0000-0000-000000000000',
        '00000000-0000-4000-8000-0000000000a2',
        'authenticated', 'authenticated', 'leo@blnd.local',
        extensions.crypt('Premium123!', extensions.gen_salt('bf')),
        now(),
        '{"provider":"email","providers":["email"]}',
        '{"email":"leo@blnd.local"}',
        now(), now(), '', '', '', ''
    ),
    (
        '00000000-0000-0000-0000-000000000000',
        '00000000-0000-4000-8000-0000000000a3',
        'authenticated', 'authenticated', 'sam@blnd.local',
        extensions.crypt('Premium123!', extensions.gen_salt('bf')),
        now(),
        '{"provider":"email","providers":["email"]}',
        '{"email":"sam@blnd.local"}',
        now(), now(), '', '', '', ''
    )
on conflict (id) do nothing;

insert into auth.identities (user_id, provider, provider_id, identity_data, created_at, updated_at)
select id, 'email', id::text,
       jsonb_build_object('sub', id::text, 'email', email, 'email_verified', true, 'phone_verified', false),
       now(), now()
from auth.users
where id in (
    '00000000-0000-4000-8000-0000000000a1',
    '00000000-0000-4000-8000-0000000000a2',
    '00000000-0000-4000-8000-0000000000a3'
)
and not exists (
    select 1 from auth.identities i
    where i.user_id = auth.users.id and i.provider = 'email'
);

insert into movies (tmdb_id, title, year, overview, poster_path, genres, runtime, vote_average, vote_count, director)
values
    (910010, 'Se7en', 1995, 'Two detectives hunt a killer.', '/se7en.jpg',
        '[{"id":53,"name":"Thriller"},{"id":80,"name":"Crime"}]', 127, 8.4, 20000, 'David Fincher'),
    (910011, 'Fight Club', 1999, 'An insomniac meets a soap salesman.', '/fight.jpg',
        '[{"id":18,"name":"Drama"}]', 139, 8.4, 28000, 'David Fincher'),
    (910012, 'Inception', 2010, 'A thief enters dreams.', '/inception.jpg',
        '[{"id":878,"name":"Science Fiction"},{"id":28,"name":"Action"}]', 148, 8.4, 35000, 'Christopher Nolan'),
    (910013, 'Midsommar', 2019, 'A summer festival goes wrong.', '/midsommar.jpg',
        '[{"id":27,"name":"Horror"}]', 148, 7.1, 8000, 'Ari Aster'),
    (910020, 'The Game', 1997, 'A banker is thrown into a game.', '/game.jpg',
        '[{"id":53,"name":"Thriller"}]', 129, 7.7, 6000, 'David Fincher'),
    (910021, 'Tenet', 2020, 'Time runs in both directions.', '/tenet.jpg',
        '[{"id":878,"name":"Science Fiction"}]', 150, 7.3, 9000, 'Christopher Nolan'),
    (910022, 'Paddington', 2014, 'A bear looks for a home.', '/paddington.jpg',
        '[{"id":35,"name":"Comedy"}]', 95, 7.2, 5000, 'Paul King')
on conflict (tmdb_id) do nothing;

do $$
declare
    maya uuid := '00000000-0000-4000-8000-0000000000a1';
    leo uuid := '00000000-0000-4000-8000-0000000000a2';
    sam uuid := '00000000-0000-4000-8000-0000000000a3';
    maya_wl bigint;
    leo_wl bigint;
    sam_wl bigint;
    friday_wl bigint;
    solo_wl bigint;
    friday_id bigint;
begin
    if not exists (select 1 from profiles where id = maya) then
        insert into watchlists default values returning id into maya_wl;
        insert into watchlists default values returning id into leo_wl;
        insert into watchlists default values returning id into sam_wl;
        insert into watchlists default values returning id into friday_wl;
        insert into watchlists default values returning id into solo_wl;

        insert into profiles (
            id, username, display_name, favorite_genres, watchlist_id,
            subscription_tier, subscription_source, subscription_expires_at
        ) values
            (maya, 'maya', 'Maya', '["Thriller","Drama"]', maya_wl, 'premium', 'admin', '2030-01-01+00'),
            (leo, 'leo', 'Leo', '["Horror","Drama"]', leo_wl, 'premium', 'admin', '2030-01-01+00'),
            (sam, 'sam', 'Sam', '["Comedy"]', sam_wl, 'free', null, null);

        insert into watched_movies (user_id, tmdb_id, rating, liked, watched_date, source) values
            (maya, 910010, 5.0, true, '2026-01-12', 'manual'),
            (maya, 910011, 5.0, true, '2026-02-03', 'manual'),
            (maya, 910012, 4.5, false, '2026-06-18', 'manual'),
            (maya, 910013, 2.0, false, '2026-10-02', 'manual'),
            (leo, 910010, 4.5, true, '2026-03-01', 'manual'),
            (leo, 910011, 1.0, false, '2026-04-09', 'manual'),
            (leo, 910013, 5.0, true, '2026-08-21', 'manual'),
            (sam, 910022, 4.0, true, '2026-05-05', 'manual');

        insert into friendships (requester_id, addressee_id, status)
        values (maya, leo, 'accepted');

        insert into groups (name, created_by, watchlist_id)
        values ('Friday Night', maya, friday_wl)
        returning id into friday_id;
        insert into group_members (group_id, user_id) values (friday_id, maya), (friday_id, leo);

        insert into groups (name, created_by, watchlist_id)
        values ('Maya Solo', maya, solo_wl);
        insert into group_members (group_id, user_id)
        select id, maya from groups where name = 'Maya Solo';
    end if;
end $$;
