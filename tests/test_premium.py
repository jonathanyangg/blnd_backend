"""blnd+ gating, year stats, match, and blend pick-tonight."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.friends.models import UserBlock
from app.groups.models import BlendVeto, GroupMember
from app.recommendations.models import HiddenMovie
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.factories import (
    make_friendship,
    make_group,
    make_movie,
    make_profile,
    make_watched,
)

FUTURE = datetime(2030, 1, 1, tzinfo=timezone.utc)
PAST = datetime(2020, 1, 1, tzinfo=timezone.utc)
DRAMA = [{"id": 18, "name": "Drama"}]
COMEDY = [{"id": 35, "name": "Comedy"}]
HORROR = [{"id": 27, "name": "Horror"}]
BLEND_GENRE = [{"id": 99, "name": "ZzzBlendGenre"}]


def _premium(db: Session, user_id: str, username: str, **kwargs):
    return make_profile(
        db,
        user_id=user_id,
        username=username,
        subscription_tier="premium",
        subscription_source=kwargs.pop("subscription_source", "apple"),
        subscription_expires_at=kwargs.pop("subscription_expires_at", FUTURE),
        **kwargs,
    )


GATED = [
    ("get", "/stats/year/2026", None),
    ("get", "/stats/genres", None),
    ("get", "/stats/directors", None),
    ("get", f"/stats/match/{TEST_USER_ID_2}", None),
    ("get", "/groups/1/pick-tonight", None),
    ("post", "/groups/1/pick-tonight/veto", {"tmdb_id": 1, "reason": "nope"}),
]


@pytest.mark.parametrize("method,path,body", GATED)
def test_free_user_gets_premium_required(
    client: TestClient, db: Session, method: str, path: str, body: dict | None
) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="freebie")
    kwargs = {"json": body} if body is not None else {}
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PREMIUM_REQUIRED"


def test_expired_premium_matches_auth_me(client: TestClient, db: Session) -> None:
    make_profile(
        db,
        user_id=TEST_USER_ID,
        username="lapsed",
        subscription_tier="premium",
        subscription_source="apple",
        subscription_expires_at=PAST,
    )
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["is_premium"] is False
    blocked = client.get("/stats/year/2026")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PREMIUM_REQUIRED"


def test_admin_grant_without_expiry_is_premium(client: TestClient, db: Session) -> None:
    make_profile(
        db,
        user_id=TEST_USER_ID,
        username="comped",
        subscription_tier="premium",
        subscription_source="admin",
        subscription_expires_at=None,
    )
    assert client.get("/auth/me").json()["is_premium"] is True
    assert client.get("/stats/year/2026").status_code == 200


def test_year_in_review(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "watcher")
    make_movie(db, tmdb_id=880001, title="Alpha", runtime=100, director="David Fincher")
    make_movie(db, tmdb_id=880002, title="Beta", runtime=50, director="David Fincher")
    make_movie(
        db,
        tmdb_id=880003,
        title="Gamma",
        runtime=120,
        director="Christopher Nolan",
        genres=COMEDY,
    )
    make_movie(db, tmdb_id=880004, title="Delta", runtime=90, director="David Fincher")
    make_movie(
        db,
        tmdb_id=880005,
        title="Epsilon",
        runtime=None,
        director=None,
        genres=HORROR,
    )
    make_watched(
        db,
        TEST_USER_ID,
        880001,
        rating=5,
        liked=True,
        watched_date=date(2026, 1, 15),
        created_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
    )
    make_watched(db, TEST_USER_ID, 880002, rating=4, watched_date=date(2026, 1, 20))
    make_watched(db, TEST_USER_ID, 880003, rating=3, watched_date=date(2026, 10, 1))
    make_watched(db, TEST_USER_ID, 880004, rating=5, watched_date=date(2025, 6, 1))
    make_watched(
        db,
        TEST_USER_ID,
        880005,
        created_at=datetime(2026, 3, 2, 15, tzinfo=timezone.utc),
    )

    data = client.get("/stats/year/2026").json()
    assert data["counts"] == {"watched": 4, "rated": 3, "liked": 1, "minutes": 270}
    assert [row["title"] for row in data["top_rated"]] == ["Alpha", "Beta", "Gamma"]
    assert data["top_genres"] == [
        {"name": "Drama", "count": 2},
        {"name": "Comedy", "count": 1},
        {"name": "Horror", "count": 1},
    ]
    assert data["top_directors"] == [
        {"name": "David Fincher", "count": 2},
        {"name": "Christopher Nolan", "count": 1},
    ]
    by_month = {row["month"]: row for row in data["monthly"]}
    assert len(by_month) == 12
    assert by_month[1] == {"month": 1, "count": 2, "minutes": 150}
    assert by_month[3] == {"month": 3, "count": 1, "minutes": 0}
    assert by_month[10] == {"month": 10, "count": 1, "minutes": 120}
    assert by_month[7] == {"month": 7, "count": 0, "minutes": 0}


def test_year_with_no_watches(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "empty")
    data = client.get("/stats/year/2024").json()
    assert data["counts"] == {"watched": 0, "rated": 0, "liked": 0, "minutes": 0}
    assert data["top_rated"] == []
    assert data["top_genres"] == []
    assert data["top_directors"] == []
    assert all(row["count"] == 0 and row["minutes"] == 0 for row in data["monthly"])


def test_genre_and_director_breakdown(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "watcher")
    make_movie(db, tmdb_id=880001, title="Alpha", runtime=100, director="David Fincher")
    make_movie(db, tmdb_id=880002, title="Beta", runtime=50, director="David Fincher")
    make_movie(db, tmdb_id=880004, title="Delta", runtime=90, director="David Fincher")
    make_movie(
        db,
        tmdb_id=880003,
        title="Gamma",
        runtime=120,
        director="Christopher Nolan",
        genres=COMEDY,
    )
    make_movie(
        db, tmdb_id=880005, title="Epsilon", runtime=None, director=None, genres=HORROR
    )
    for tmdb_id, rating in (
        (880001, 5),
        (880002, 4),
        (880004, 5),
        (880003, 3),
        (880005, None),
    ):
        make_watched(db, TEST_USER_ID, tmdb_id, rating=rating)

    genres = client.get("/stats/genres").json()["genres"]
    assert genres[0] == {
        "name": "Drama",
        "count": 3,
        "avg_rating": 4.67,
        "minutes": 240,
    }
    directors = client.get("/stats/directors").json()["directors"]
    assert directors[0]["name"] == "David Fincher"
    assert directors[0]["count"] == 3
    assert directors[0]["minutes"] == 240
    assert "Epsilon" not in [row["name"] for row in directors]


def test_match_explanation(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "me")
    make_profile(db, user_id=TEST_USER_ID_2, username="them")
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    make_movie(db, tmdb_id=880101, title="Both Love")
    make_movie(db, tmdb_id=880102, title="Split")
    make_movie(db, tmdb_id=880103, title="Private Mine")
    make_movie(db, tmdb_id=880104, title="Private Theirs")
    make_watched(db, TEST_USER_ID, 880101, rating=5)
    make_watched(db, TEST_USER_ID_2, 880101, rating=5)
    make_watched(db, TEST_USER_ID, 880102, rating=5)
    make_watched(db, TEST_USER_ID_2, 880102, rating=1)
    make_watched(db, TEST_USER_ID, 880103, rating=5)
    make_watched(db, TEST_USER_ID_2, 880104, rating=1)

    resp = client.get(f"/stats/match/{TEST_USER_ID_2}")
    assert resp.status_code == 200
    data = resp.json()
    # mae of (0, 4) is 2; 0.7 * (1 - 2/4.5) + 0.3 * 1 genre cosine = 69
    assert data["match_percent"] == 69
    assert [row["title"] for row in data["shared_high_ratings"]] == ["Both Love"]
    assert [row["title"] for row in data["biggest_disagreements"]] == ["Split"]
    assert data["genre_overlap"][0]["name"] == "Drama"
    blob = json.dumps(data)
    assert "Private Mine" not in blob
    assert "Private Theirs" not in blob


def test_match_identical_ratings_is_100(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "me")
    make_profile(db, user_id=TEST_USER_ID_2, username="them")
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    make_movie(db, tmdb_id=880111, title="Same")
    make_watched(db, TEST_USER_ID, 880111, rating=5)
    make_watched(db, TEST_USER_ID_2, 880111, rating=5)
    data = client.get(f"/stats/match/{TEST_USER_ID_2}").json()
    assert data["match_percent"] == 100


def test_match_with_no_ratings(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "me")
    make_profile(db, user_id=TEST_USER_ID_2, username="them")
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    data = client.get(f"/stats/match/{TEST_USER_ID_2}").json()
    assert data["match_percent"] == 0
    assert data["shared_high_ratings"] == []
    assert data["genre_overlap"] == []
    assert data["biggest_disagreements"] == []


def test_match_requires_friendship(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "me")
    make_profile(db, user_id=TEST_USER_ID_2, username="them")
    make_movie(db, tmdb_id=880121, title="Secret Title")
    make_watched(db, TEST_USER_ID_2, 880121, rating=5)
    resp = client.get(f"/stats/match/{TEST_USER_ID_2}")
    assert resp.status_code == 403
    assert "Secret Title" not in resp.text


def test_match_hides_user_who_blocked_caller(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "me")
    make_profile(db, user_id=TEST_USER_ID_2, username="them")
    db.add(UserBlock(blocker_id=TEST_USER_ID_2, blocked_id=TEST_USER_ID))
    db.commit()
    resp = client.get(f"/stats/match/{TEST_USER_ID_2}")
    assert resp.status_code == 404


def test_match_self_is_rejected(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "me")
    resp = client.get(f"/stats/match/{TEST_USER_ID}")
    assert resp.status_code == 400


def _blend_with_taste(db: Session, *, second_member: bool) -> tuple[int, int, int]:
    """Caller loved one title. Two unwatched films: a closer match and a popular one."""
    _premium(db, TEST_USER_ID, "host")
    if second_member:
        make_profile(db, user_id=TEST_USER_ID_2, username="guest")
    group, _wl = make_group(db, name="Friday", created_by=TEST_USER_ID)
    if second_member:
        db.add(GroupMember(group_id=group.id, user_id=TEST_USER_ID_2))
        db.commit()
    make_movie(
        db,
        tmdb_id=880201,
        title="Loved",
        director="Zzz Blend Director",
        genres=BLEND_GENRE,
        vote_average=6,
    )
    make_movie(
        db,
        tmdb_id=880202,
        title="Pick Me",
        director="Zzz Blend Director",
        genres=BLEND_GENRE,
        vote_average=7,
    )
    make_movie(
        db,
        tmdb_id=880203,
        title="Second",
        director="Someone Else",
        genres=BLEND_GENRE,
        vote_average=9,
    )
    make_watched(db, TEST_USER_ID, 880201, rating=5)
    return group.id, 880202, 880203


def test_pick_tonight_from_taste(client: TestClient, db: Session) -> None:
    group_id, winner, _second = _blend_with_taste(db, second_member=True)
    first = client.get(f"/groups/{group_id}/pick-tonight")
    assert first.status_code == 200
    assert first.json()["pick"]["tmdb_id"] == winner
    again = client.get(f"/groups/{group_id}/pick-tonight")
    assert again.json()["pick"]["tmdb_id"] == winner
    stored = db.execute(
        text("SELECT COUNT(*) FROM blend_picks WHERE group_id = :group_id"),
        {"group_id": group_id},
    ).scalar()
    assert stored == 1


def test_pick_tonight_single_member(client: TestClient, db: Session) -> None:
    group_id, winner, _second = _blend_with_taste(db, second_member=False)
    resp = client.get(f"/groups/{group_id}/pick-tonight")
    assert resp.status_code == 200
    assert resp.json()["pick"]["tmdb_id"] == winner


def test_veto_repicks_and_stores_reason(client: TestClient, db: Session) -> None:
    group_id, winner, second = _blend_with_taste(db, second_member=True)
    assert (
        client.get(f"/groups/{group_id}/pick-tonight").json()["pick"]["tmdb_id"]
        == winner
    )
    vetoed = client.post(
        f"/groups/{group_id}/pick-tonight/veto",
        json={"tmdb_id": winner, "reason": "already saw it"},
    )
    assert vetoed.status_code == 200
    body = vetoed.json()
    assert body["pick"]["tmdb_id"] == second
    assert body["vetoes"][0]["reason"] == "already saw it"
    assert body["vetoes"][0]["tmdb_id"] == winner
    assert body["vetoes"][0]["username"] == "host"
    again = client.get(f"/groups/{group_id}/pick-tonight")
    assert again.json()["pick"]["tmdb_id"] == second


def test_yesterdays_veto_does_not_block_today(client: TestClient, db: Session) -> None:
    group_id, winner, _second = _blend_with_taste(db, second_member=False)
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    db.add(
        BlendVeto(
            group_id=group_id,
            veto_date=yesterday,
            user_id=TEST_USER_ID,
            tmdb_id=winner,
            reason="not tonight",
        )
    )
    db.commit()
    resp = client.get(f"/groups/{group_id}/pick-tonight")
    assert resp.json()["pick"]["tmdb_id"] == winner
    assert resp.json()["vetoes"] == []


def test_hidden_movie_is_not_picked(client: TestClient, db: Session) -> None:
    group_id, winner, second = _blend_with_taste(db, second_member=False)
    db.add(HiddenMovie(user_id=TEST_USER_ID, tmdb_id=winner))
    db.commit()
    resp = client.get(f"/groups/{group_id}/pick-tonight")
    assert resp.json()["pick"]["tmdb_id"] == second


def test_pick_with_no_ratings_uses_popularity(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "host")
    group, _wl = make_group(db, name="Solo", created_by=TEST_USER_ID)
    make_movie(db, tmdb_id=880301, title="Quiet", vote_average=6.0, vote_count=10)
    make_movie(
        db, tmdb_id=880302, title="Loud", vote_average=10.0, vote_count=9_999_999
    )
    resp = client.get(f"/groups/{group.id}/pick-tonight")
    assert resp.status_code == 200
    best = db.execute(
        text(
            """
            SELECT tmdb_id FROM movies
            ORDER BY vote_average DESC NULLS LAST,
                     COALESCE(vote_count, 0) DESC,
                     tmdb_id
            LIMIT 1
            """
        )
    ).scalar()
    assert resp.json()["pick"]["tmdb_id"] == best


def test_pick_is_null_when_every_title_is_watched(
    client: TestClient, db: Session
) -> None:
    _premium(db, TEST_USER_ID, "host")
    group, _wl = make_group(db, name="Done", created_by=TEST_USER_ID)
    ids = [row[0] for row in db.execute(text("SELECT tmdb_id FROM movies")).all()]
    for tmdb_id in ids:
        make_watched(db, TEST_USER_ID, tmdb_id)
    resp = client.get(f"/groups/{group.id}/pick-tonight")
    assert resp.status_code == 200
    assert resp.json()["pick"] is None


def test_pick_requires_membership(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "host")
    make_profile(
        db,
        user_id=TEST_USER_ID_2,
        username="outsider",
        subscription_tier="premium",
        subscription_source="apple",
        subscription_expires_at=FUTURE,
    )
    group, _wl = make_group(db, name="Private", created_by=TEST_USER_ID_2)
    resp = client.get(f"/groups/{group.id}/pick-tonight")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not a member of this group"


def test_pick_missing_group(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "host")
    resp = client.get("/groups/999999/pick-tonight")
    assert resp.status_code == 404


def test_veto_unknown_movie(client: TestClient, db: Session) -> None:
    _premium(db, TEST_USER_ID, "host")
    group, _wl = make_group(db, name="Friday", created_by=TEST_USER_ID)
    resp = client.post(
        f"/groups/{group.id}/pick-tonight/veto",
        json={"tmdb_id": 880999, "reason": "no such film"},
    )
    assert resp.status_code == 404
