"""Unnamed blends show member first names. The stored name stays null."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.groups.models import Group
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.factories import make_profile


def test_unnamed_blend_uses_member_first_names(
    client: TestClient, db: Session
) -> None:
    make_profile(
        db, user_id=TEST_USER_ID, username="alex", display_name="Alex Smith"
    )
    make_profile(db, user_id=TEST_USER_ID_2, username="sam", display_name="Sam Lee")
    make_profile(
        db,
        user_id="33333333-3333-3333-3333-333333333333",
        username="jo",
        display_name="Jo Park",
    )
    make_profile(
        db,
        user_id="44444444-4444-4444-4444-444444444444",
        username="max",
        display_name="Max Ng",
    )

    created = client.post("/groups/", json={})
    assert created.status_code == 200
    body = created.json()
    assert body["name"] is None
    assert body["display_name"] == "Alex"
    group_id = body["id"]
    assert db.query(Group).filter(Group.id == group_id).one().name is None

    client.post(f"/groups/{group_id}/members", json={"username": "sam"})
    two = client.get(f"/groups/{group_id}")
    assert two.json()["name"] is None
    assert two.json()["display_name"] == "Alex & Sam"

    client.post(f"/groups/{group_id}/members", json={"username": "jo"})
    three = client.get(f"/groups/{group_id}")
    assert three.json()["display_name"] == "Alex, Sam & 1 other"

    client.post(f"/groups/{group_id}/members", json={"username": "max"})
    four = client.get(f"/groups/{group_id}")
    assert four.json()["display_name"] == "Alex, Sam & 2 others"
    assert db.query(Group).filter(Group.id == group_id).one().name is None


def test_explicit_name_is_stored_and_shown(client: TestClient, db: Session) -> None:
    make_profile(
        db, user_id=TEST_USER_ID, username="alex", display_name="Alex Smith"
    )
    created = client.post("/groups/", json={"name": "Friday Crew"})
    assert created.status_code == 200
    assert created.json()["name"] == "Friday Crew"
    assert created.json()["display_name"] == "Friday Crew"
    listed = client.get("/groups/")
    assert listed.json()["groups"][0]["display_name"] == "Friday Crew"
