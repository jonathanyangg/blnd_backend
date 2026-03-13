from unittest.mock import MagicMock


from tests.conftest import CALLER_ID, TARGET_ID  # noqa: F401


def _make_friendship_mock() -> MagicMock:
    m = MagicMock()
    m.status = "accepted"
    return m


def _make_profile_mock() -> MagicMock:
    m = MagicMock()
    m.id = TARGET_ID
    m.username = "friend"
    m.display_name = "Friend User"
    m.avatar_url = None
    return m


def test_get_public_profile_success(app_client: MagicMock, mock_db: MagicMock) -> None:
    """GET /auth/users/{id}/profile returns 200 with 7 public fields, no private fields."""
    friendship = _make_friendship_mock()
    profile = _make_profile_mock()

    # first() calls: [friendship_check, profile_lookup]
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        friendship,
        profile,
    ]
    # scalar() calls: [watched_count, friends_count, blends_count]
    mock_db.query.return_value.filter.return_value.scalar.side_effect = [5, 3, 2]

    response = app_client.get(f"/auth/users/{TARGET_ID}/profile")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == TARGET_ID
    assert data["username"] == "friend"
    assert data["display_name"] == "Friend User"
    assert data["avatar_url"] is None
    assert data["watched_count"] == 5
    assert data["friends_count"] == 3
    assert data["blends_count"] == 2
    assert "taste_bio" not in data
    assert "favorite_genres" not in data


def test_public_profile_403_not_friends(
    app_client: MagicMock, mock_db: MagicMock
) -> None:
    """GET /auth/users/{id}/profile returns 403 when no accepted friendship exists."""
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = app_client.get(f"/auth/users/{TARGET_ID}/profile")

    assert response.status_code == 403
    assert response.json()["detail"] == "Not friends with this user"


def test_public_profile_404_user_not_found(
    app_client: MagicMock, mock_db: MagicMock
) -> None:
    """GET /auth/users/{id}/profile returns 404 when target profile doesn't exist."""
    friendship = _make_friendship_mock()
    # first() calls: [friendship passes, profile not found]
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        friendship,
        None,
    ]

    response = app_client.get(f"/auth/users/{TARGET_ID}/profile")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Plan 02: Watched movies endpoint
# ---------------------------------------------------------------------------


def test_get_public_watched_success(app_client: MagicMock, mock_db: MagicMock) -> None:
    """GET /auth/users/{id}/watched returns 200 with paginated watched movies."""
    friendship = _make_friendship_mock()

    # friendship check — first()
    mock_db.query.return_value.filter.return_value.first.return_value = friendship

    # scalar() for total count
    mock_db.query.return_value.filter.return_value.scalar.return_value = 3

    # Build mock (WatchedMovie, Movie) tuples
    wm1 = MagicMock()
    wm1.tmdb_id = 550
    wm1.rating = 4.5
    mv1 = MagicMock()
    mv1.title = "Fight Club"
    mv1.poster_path = "/fc.jpg"

    wm2 = MagicMock()
    wm2.tmdb_id = 680
    wm2.rating = 3.0
    mv2 = MagicMock()
    mv2.title = "Pulp Fiction"
    mv2.poster_path = "/pf.jpg"

    (
        mock_db.query.return_value.join.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value
    ) = [(wm1, mv1), (wm2, mv2)]

    response = app_client.get(f"/auth/users/{TARGET_ID}/watched?limit=20&offset=0")

    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "total" in data
    assert data["total"] == 3
    assert len(data["results"]) == 2
    for item in data["results"]:
        assert "tmdb_id" in item
        assert "title" in item
        assert "poster_path" in item
        assert "rating" in item


def test_get_public_watched_403(app_client: MagicMock, mock_db: MagicMock) -> None:
    """GET /auth/users/{id}/watched returns 403 when not friends."""
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = app_client.get(f"/auth/users/{TARGET_ID}/watched")

    assert response.status_code == 403
    assert response.json()["detail"] == "Not friends with this user"


def test_get_public_watched_pagination(
    app_client: MagicMock, mock_db: MagicMock
) -> None:
    """GET /auth/users/{id}/watched?limit=2 accepts pagination params."""
    friendship = _make_friendship_mock()
    mock_db.query.return_value.filter.return_value.first.return_value = friendship
    mock_db.query.return_value.filter.return_value.scalar.return_value = 5

    wm = MagicMock()
    wm.tmdb_id = 100
    wm.rating = 4.0
    mv = MagicMock()
    mv.title = "Test Movie"
    mv.poster_path = "/t.jpg"

    (
        mock_db.query.return_value.join.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value
    ) = [(wm, mv)]

    response = app_client.get(f"/auth/users/{TARGET_ID}/watched?limit=2&offset=0")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Plan 02: Friends list endpoint
# ---------------------------------------------------------------------------


def test_get_public_friends_success(app_client: MagicMock, mock_db: MagicMock) -> None:
    """GET /auth/users/{id}/friends returns 200 with friends list."""
    FRIEND_A = "33333333-3333-3333-3333-333333333333"
    FRIEND_B = "44444444-4444-4444-4444-444444444444"

    friendship = _make_friendship_mock()
    mock_db.query.return_value.filter.return_value.first.return_value = friendship

    # Two friendships for the listing query
    fs1 = MagicMock()
    fs1.requester_id = TARGET_ID
    fs1.addressee_id = FRIEND_A

    fs2 = MagicMock()
    fs2.requester_id = FRIEND_B
    fs2.addressee_id = TARGET_ID

    mock_db.query.return_value.filter.return_value.all.return_value = [fs1, fs2]

    # Profile lookup for each friend
    p_a = MagicMock()
    p_a.id = FRIEND_A
    p_a.username = "friend_a"
    p_a.display_name = "Friend A"
    p_a.avatar_url = None

    p_b = MagicMock()
    p_b.id = FRIEND_B
    p_b.username = "friend_b"
    p_b.display_name = "Friend B"
    p_b.avatar_url = "https://example.com/b.jpg"

    mock_db.query.return_value.filter.return_value.first.side_effect = [
        friendship,
        p_a,
        p_b,
    ]

    response = app_client.get(f"/auth/users/{TARGET_ID}/friends")

    assert response.status_code == 200
    data = response.json()
    assert "friends" in data
    assert len(data["friends"]) == 2
    for f in data["friends"]:
        assert "id" in f
        assert "username" in f
        assert "display_name" in f
        assert "avatar_url" in f


def test_get_public_friends_403(app_client: MagicMock, mock_db: MagicMock) -> None:
    """GET /auth/users/{id}/friends returns 403 when not friends."""
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = app_client.get(f"/auth/users/{TARGET_ID}/friends")

    assert response.status_code == 403
    assert response.json()["detail"] == "Not friends with this user"


def test_get_public_friends_empty(app_client: MagicMock, mock_db: MagicMock) -> None:
    """GET /auth/users/{id}/friends returns empty list when target has no friends."""
    friendship = _make_friendship_mock()
    mock_db.query.return_value.filter.return_value.first.return_value = friendship
    mock_db.query.return_value.filter.return_value.all.return_value = []

    response = app_client.get(f"/auth/users/{TARGET_ID}/friends")

    assert response.status_code == 200
    assert response.json() == {"friends": []}
