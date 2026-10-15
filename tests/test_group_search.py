"""Blend search on GET /groups. Only blends the caller belongs to."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.groups.models import GroupMember
from app.groups.names import default_blend_name
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.factories import make_group, make_profile


def test_default_blend_name_shapes() -> None:
    assert default_blend_name(["Alex"]) == "Alex"
    assert default_blend_name(["Alex", "Sam"]) == "Alex & Sam"
    assert default_blend_name(["Alex", "Sam", "Jo"]) == "Alex, Sam & 1 other"
    assert default_blend_name(["Alex", "Sam", "Jo", "Max"]) == "Alex, Sam & 2 others"


def test_group_search_matches_stored_name_and_default_member_names(
    client: TestClient, db: Session
) -> None:
    make_profile(
        db, user_id=TEST_USER_ID, username="alex", display_name="Alex Smith"
    )
    make_profile(db, user_id=TEST_USER_ID_2, username="sam", display_name="Sam Lee")
    group, _ = make_group(db, name="Friday Crew", created_by=TEST_USER_ID)
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    db.add(GroupMember(group_id=group.id, user_id=TEST_USER_ID_2, joined_at=later))
    db.commit()

    # Someone else's blend, even if the name matches.
    make_profile(
        db,
        user_id="33333333-3333-3333-3333-333333333333",
        username="outsider",
        display_name="Alex Outsider",
    )
    make_group(
        db, name="Alex Private", created_by="33333333-3333-3333-3333-333333333333"
    )

    by_stored = client.get("/groups/", params={"q": "friday"})
    assert by_stored.status_code == 200
    body = by_stored.json()
    assert body["total"] == 1
    assert body["groups"][0]["name"] == "Friday Crew"
    assert body["groups"][0]["display_name"] == "Friday Crew"

    by_members = client.get("/groups/", params={"q": "alex & sam"})
    assert by_members.status_code == 200
    assert by_members.json()["total"] == 1
    assert by_members.json()["groups"][0]["id"] == group.id

    missing = client.get("/groups/", params={"q": "private"})
    assert missing.json()["groups"] == []
    assert missing.json()["total"] == 0


def test_group_list_without_query_stays_unpaginated(
    client: TestClient, db: Session
) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="alex", display_name="Alex")
    make_group(db, name="One", created_by=TEST_USER_ID)
    make_group(db, name="Two", created_by=TEST_USER_ID)
    resp = client.get("/groups/")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["groups"]) == 2
    assert "total" not in body
    assert {group["display_name"] for group in body["groups"]} == {"One", "Two"}


def test_group_search_paginates(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="alex", display_name="Alex")
    make_group(db, name="Alpha Night", created_by=TEST_USER_ID)
    make_group(db, name="Beta Night", created_by=TEST_USER_ID)
    first = client.get("/groups/", params={"q": "night", "limit": 1, "offset": 0})
    second = client.get("/groups/", params={"q": "night", "limit": 1, "offset": 1})
    assert first.json()["total"] == 2
    assert len(first.json()["groups"]) == 1
    assert len(second.json()["groups"]) == 1
    assert first.json()["groups"][0]["id"] != second.json()["groups"][0]["id"]
