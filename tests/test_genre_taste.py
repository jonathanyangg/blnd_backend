"""Tests for GET /auth/me/taste genre taste endpoint (Phase 10, Plan 01)."""

from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rows(*tuples: tuple) -> list:
    """Convert plain tuples to mock Row objects with index access."""
    rows = []
    for genres, rating in tuples:
        row = MagicMock()
        row.__iter__ = MagicMock(return_value=iter((genres, rating)))
        # Support tuple unpacking via __getitem__
        row.__getitem__ = MagicMock(side_effect=lambda i, g=genres, r=rating: (g, r)[i])
        rows.append((genres, rating))
    return rows


# ---------------------------------------------------------------------------
# Test 1: Success path — 2 movies, Action x2, Sci-Fi x1
# ---------------------------------------------------------------------------


def test_genre_taste_success(app_client: MagicMock, mock_db: MagicMock) -> None:
    """GET /auth/me/taste returns 200 with exactly 8 genres in fixed order.

    Action has watch_count=2, Sci-Fi has watch_count=1 (via alias from 'Science Fiction').
    Other 6 genres have score=0.0, watch_count=0.
    """
    rows = [
        ([{"id": 28, "name": "Action"}, {"id": 878, "name": "Science Fiction"}], 4.5),
        ([{"id": 28, "name": "Action"}], 3.5),
    ]
    mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = rows

    response = app_client.get("/auth/me/taste")

    assert response.status_code == 200
    data = response.json()
    assert "genres" in data
    assert len(data["genres"]) == 8

    # Fixed order: Action first
    names = [g["name"] for g in data["genres"]]
    assert names == [
        "Action",
        "Comedy",
        "Drama",
        "Horror",
        "Sci-Fi",
        "Romance",
        "Thriller",
        "Animation",
    ]

    action = next(g for g in data["genres"] if g["name"] == "Action")
    scifi = next(g for g in data["genres"] if g["name"] == "Sci-Fi")
    comedy = next(g for g in data["genres"] if g["name"] == "Comedy")

    assert action["watch_count"] == 2
    assert scifi["watch_count"] == 1
    assert scifi["score"] > 0.0, "Sci-Fi alias must produce non-zero score"
    assert comedy["watch_count"] == 0
    assert comedy["score"] == 0.0


# ---------------------------------------------------------------------------
# Test 2: New user — empty watch history
# ---------------------------------------------------------------------------


def test_genre_taste_new_user(app_client: MagicMock, mock_db: MagicMock) -> None:
    """GET /auth/me/taste with empty watch history returns 200, 8 genres all zeroed."""
    mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = []

    response = app_client.get("/auth/me/taste")

    assert response.status_code == 200
    data = response.json()
    assert len(data["genres"]) == 8
    assert data["total_rated"] == 0
    for g in data["genres"]:
        assert g["score"] == 0.0
        assert g["watch_count"] == 0
        assert g["avg_rating"] is None


# ---------------------------------------------------------------------------
# Test 3: Sci-Fi alias — only Science Fiction movies watched
# ---------------------------------------------------------------------------


def test_genre_taste_sci_fi_alias(app_client: MagicMock, mock_db: MagicMock) -> None:
    """'Science Fiction' genre maps to 'Sci-Fi' axis with non-zero score."""
    rows = [
        ([{"id": 878, "name": "Science Fiction"}], 4.0),
    ]
    mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = rows

    response = app_client.get("/auth/me/taste")

    assert response.status_code == 200
    data = response.json()
    scifi = next(g for g in data["genres"] if g["name"] == "Sci-Fi")
    assert scifi["watch_count"] == 1
    assert scifi["score"] > 0.0


# ---------------------------------------------------------------------------
# Test 4: Normalization — Action:10 watches, Comedy:5 watches
# ---------------------------------------------------------------------------


def test_genre_taste_normalization(app_client: MagicMock, mock_db: MagicMock) -> None:
    """Action freq=1.0 (max), Comedy freq=0.5 → Action score > Comedy score."""
    action_rows = [([{"id": 28, "name": "Action"}], 4.0)] * 10
    comedy_rows = [([{"id": 35, "name": "Comedy"}], 4.0)] * 5
    rows = action_rows + comedy_rows
    mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = rows

    response = app_client.get("/auth/me/taste")

    assert response.status_code == 200
    data = response.json()
    action = next(g for g in data["genres"] if g["name"] == "Action")
    comedy = next(g for g in data["genres"] if g["name"] == "Comedy")
    assert action["score"] > comedy["score"]
    assert action["watch_count"] == 10
    assert comedy["watch_count"] == 5


# ---------------------------------------------------------------------------
# Test 5: Score formula — exact math check
# ---------------------------------------------------------------------------


def test_genre_taste_score_formula(app_client: MagicMock, mock_db: MagicMock) -> None:
    """Score = round(0.60 * freq + 0.40 * norm_rating, 4), norm_rating = (avg-0.5)/4.5."""
    # Only Action movies watched (so Action freq = 1.0)
    # 2 movies, ratings 4.5 and 3.5 → avg = 4.0
    rows = [
        ([{"id": 28, "name": "Action"}], 4.5),
        ([{"id": 28, "name": "Action"}], 3.5),
    ]
    mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = rows

    response = app_client.get("/auth/me/taste")

    assert response.status_code == 200
    data = response.json()
    action = next(g for g in data["genres"] if g["name"] == "Action")

    # Expected: freq=1.0, avg_rating=4.0, norm_rating=(4.0-0.5)/4.5 = 3.5/4.5 ≈ 0.7778
    avg_r = 4.0
    norm_rating = (avg_r - 0.5) / 4.5
    expected_score = round(0.60 * 1.0 + 0.40 * norm_rating, 4)

    assert action["score"] == expected_score
    assert action["avg_rating"] == round(4.0, 2)


# ---------------------------------------------------------------------------
# Test 6: Raw fields — all 4 fields present on each entry + total_rated
# ---------------------------------------------------------------------------


def test_genre_taste_raw_fields(app_client: MagicMock, mock_db: MagicMock) -> None:
    """Each genre entry has name, score, watch_count, avg_rating. total_rated present."""
    rows = [
        ([{"id": 28, "name": "Action"}], 3.0),
    ]
    mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = rows

    response = app_client.get("/auth/me/taste")

    assert response.status_code == 200
    data = response.json()
    assert "total_rated" in data
    assert data["total_rated"] == 1
    for g in data["genres"]:
        assert "name" in g
        assert "score" in g
        assert "watch_count" in g
        assert "avg_rating" in g
        assert isinstance(g["name"], str)
        assert isinstance(g["score"], float)
        assert isinstance(g["watch_count"], int)


# ---------------------------------------------------------------------------
# Test 7: Unrated watches — watched but never rated → norm_rating = 0.5
# ---------------------------------------------------------------------------


def test_genre_taste_unrated_watches(app_client: MagicMock, mock_db: MagicMock) -> None:
    """3 Action watches, all unrated → avg_rating=null, norm_rating=0.5.

    Expected score = 0.60*1.0 + 0.40*0.5 = 0.80.
    """
    rows = [
        ([{"id": 28, "name": "Action"}], None),
        ([{"id": 28, "name": "Action"}], None),
        ([{"id": 28, "name": "Action"}], None),
    ]
    mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = rows

    response = app_client.get("/auth/me/taste")

    assert response.status_code == 200
    data = response.json()
    action = next(g for g in data["genres"] if g["name"] == "Action")

    assert action["watch_count"] == 3
    assert action["avg_rating"] is None
    assert action["score"] == round(0.60 * 1.0 + 0.40 * 0.5, 4)  # 0.80
    assert data["total_rated"] == 0
