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
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'comment_like',
        'a4a4a4a4-a4a4-a4a4-a4a4-a4a4a4a4a4a4', 'New Like', 'Riley liked your review',
        '{"type":"comment_like","comment_id":"1","tmdb_id":"550","poster_path":"/poster.jpg"}'::jsonb,
        'like:comment:1', now() - interval '8 minutes'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'comment_like',
        'a3a3a3a3-a3a3-a3a3-a3a3-a3a3a3a3a3a3', 'New Like', 'Jordan liked your review',
        '{"type":"comment_like","comment_id":"1","tmdb_id":"550","poster_path":"/poster.jpg"}'::jsonb,
        'like:comment:1', now() - interval '7 minutes'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'comment_like',
        'a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2', 'New Like', 'Sam liked your review',
        '{"type":"comment_like","comment_id":"1","tmdb_id":"550","poster_path":"/poster.jpg"}'::jsonb,
        'like:comment:1', now() - interval '6 minutes'
    ),
    (
        'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'comment_like',
        'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'New Like', 'Alex liked your review',
        '{"type":"comment_like","comment_id":"1","tmdb_id":"550","poster_path":"/poster.jpg"}'::jsonb,
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
