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

-- Demo notification center for the local Casey account.
-- watched_with rows are written by notify_watched_with(), which PR #19 calls
-- when a log tags someone. One demo row is included so the inbox shows the type.

INSERT INTO auth.users (id, instance_id, aud, role, email, created_at, updated_at)
VALUES
    ('c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'demo_casey@test.local', now(), now()),
    ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'demo_alex@test.local', now(), now()),
    ('a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'demo_sam@test.local', now(), now()),
    ('a3a3a3a3-a3a3-a3a3-a3a3-a3a3a3a3a3a3', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'demo_jordan@test.local', now(), now()),
    ('a4a4a4a4-a4a4-a4a4-a4a4-a4a4a4a4a4a4', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'demo_riley@test.local', now(), now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO profiles (id, username, display_name)
VALUES
    ('c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'demo_casey', 'Casey'),
    ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'demo_alex', 'Alex'),
    ('a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2', 'demo_sam', 'Sam'),
    ('a3a3a3a3-a3a3-a3a3-a3a3-a3a3a3a3a3a3', 'demo_jordan', 'Jordan'),
    ('a4a4a4a4-a4a4-a4a4-a4a4-a4a4a4a4a4a4', 'demo_riley', 'Riley')
ON CONFLICT (id) DO NOTHING;

INSERT INTO friendships (requester_id, addressee_id, status)
VALUES
    (
        'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1',
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1',
        'pending'
    ),
    (
        'a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2',
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1',
        'accepted'
    );

INSERT INTO notification_inbox (
    user_id, type, from_user_id, title, body, data, read, created_at
)
SELECT
    'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1',
    'friend_request',
    'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1',
    'Friend Request',
    'demo_alex sent you a friend request',
    jsonb_build_object(
        'type', 'friend_request',
        'user_id', 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1',
        'friendship_id', f.id::text
    ),
    false,
    now()
FROM friendships f
WHERE f.requester_id = 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1'
  AND f.addressee_id = 'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1';

INSERT INTO notification_inbox (
    user_id, type, from_user_id, title, body, data, group_key, created_at
)
VALUES
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'like',
        'a4a4a4a4-a4a4-a4a4-a4a4-a4a4a4a4a4a4', 'New Like', 'Riley liked your review',
        '{"type":"like","comment_id":"1","tmdb_id":"550","poster_path":"/poster.jpg"}'::jsonb,
        'like:comment:1', now() - interval '8 minutes'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'like',
        'a3a3a3a3-a3a3-a3a3-a3a3-a3a3a3a3a3a3', 'New Like', 'Jordan liked your review',
        '{"type":"like","comment_id":"1","tmdb_id":"550","poster_path":"/poster.jpg"}'::jsonb,
        'like:comment:1', now() - interval '7 minutes'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'like',
        'a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2', 'New Like', 'Sam liked your review',
        '{"type":"like","comment_id":"1","tmdb_id":"550","poster_path":"/poster.jpg"}'::jsonb,
        'like:comment:1', now() - interval '6 minutes'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'like',
        'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'New Like', 'Alex liked your review',
        '{"type":"like","comment_id":"1","tmdb_id":"550","poster_path":"/poster.jpg"}'::jsonb,
        'like:comment:1', now() - interval '5 minutes'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'group_invite',
        'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'Added to Blend',
        'demo_alex added you to Weekend Blend',
        '{"type":"group_invite","group_id":"1"}'::jsonb,
        NULL, now() - interval '4 minutes'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'group_watchlist',
        'a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2', 'Weekend Blend',
        'demo_sam added Fight Club to the watchlist',
        '{"type":"group_watchlist","group_id":"1","tmdb_id":"550"}'::jsonb,
        NULL, now() - interval '3 minutes'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'comment_reply',
        'a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2', 'New Reply',
        'demo_sam replied to your comment on Fight Club',
        '{"type":"comment_reply","tmdb_id":"550","comment_id":"1"}'::jsonb,
        NULL, now() - interval '2 minutes'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'comment_mention',
        'a3a3a3a3-a3a3-a3a3-a3a3-a3a3a3a3a3a3', 'New Mention',
        'demo_jordan mentioned you in a comment on Fight Club',
        '{"type":"comment_mention","tmdb_id":"550","comment_id":"1"}'::jsonb,
        NULL, now() - interval '90 seconds'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'friend_activity',
        'a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2', 'Friend Activity',
        'demo_sam rated Fight Club ★ 4.5',
        '{"type":"friend_activity","tmdb_id":"550","movie_title":"Fight Club"}'::jsonb,
        'rating:550', now() - interval '80 seconds'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'recommendation',
        NULL, 'A match for you',
        'Fight Club is a 92% match',
        '{"type":"recommendation","tmdb_id":"550"}'::jsonb,
        NULL, now() - interval '60 seconds'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'watched_with',
        'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'Watched with you',
        'Alex watched Fight Club with you',
        '{"type":"watched_with","tmdb_id":"550","user_id":"a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1","poster_path":"/poster.jpg"}'::jsonb,
        'watched_with:550', now() - interval '40 seconds'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'match',
        NULL, 'New match',
        'You and demo_alex both love Fight Club',
        '{"type":"match","tmdb_id":"550"}'::jsonb,
        NULL, now() - interval '30 seconds'
    );
