"""Hashed phone storage. Clients send raw E.164; the database stores HMAC only."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.core.phone import hash_phone, normalize_e164
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2, assert_error
from tests.factories import make_profile

RAW = "+15551234567"
PRETTY = "+1 (555) 123-4567"


@pytest.fixture(autouse=True)
def _hash_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "contact_hash_key", "test-contact-key")


def test_normalize_strips_separators() -> None:
    assert normalize_e164(PRETTY) == RAW


def test_hash_is_not_the_raw_number() -> None:
    digest = hash_phone(PRETTY)
    assert digest != RAW
    assert RAW not in digest
    assert digest == hash_phone(RAW)


def test_profile_stores_hash_and_response_omits_it(
    client: TestClient, db: Session
) -> None:
    from app.auth.models import Profile

    make_profile(db, user_id=TEST_USER_ID, username="phoneuser")
    resp = client.patch("/auth/profile", json={"phone_number": PRETTY})
    assert resp.status_code == 200
    assert resp.json()["phone_number"] is None

    stored = db.query(Profile).filter(Profile.id == TEST_USER_ID).one().phone_number
    assert stored == hash_phone(RAW)
    assert "555" not in (stored or "")

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["phone_number"] is None


def test_contacts_match_on_hash(client: TestClient, db: Session) -> None:
    from app.auth.models import Profile
    from app.friends.models import UserContact

    make_profile(db, user_id=TEST_USER_ID, username="uploader")
    owner = make_profile(db, user_id=TEST_USER_ID_2, username="owner")
    owner.phone_number = hash_phone(RAW)
    db.commit()

    uploaded = client.post(
        "/friends/contacts", json={"phone_numbers": [PRETTY, PRETTY]}
    )
    assert uploaded.status_code == 204

    row = db.query(UserContact).filter(UserContact.user_id == TEST_USER_ID).one()
    assert row.contact_phone == hash_phone(RAW)
    assert db.query(Profile).filter(
        Profile.id == TEST_USER_ID_2
    ).one().phone_number == (row.contact_phone)

    suggestions = client.get("/friends/suggestions")
    assert suggestions.status_code == 200
    matches = suggestions.json()["contacts"]
    assert [item["username"] for item in matches] == ["owner"]


def test_invalid_contact_phone_is_rejected(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="uploader")
    resp = client.post("/friends/contacts", json={"phone_numbers": ["5551234567"]})
    assert_error(resp, status=422, code="VALIDATION_ERROR", contains="E.164")


def test_same_phone_cannot_belong_to_two_profiles(
    client: TestClient, db: Session
) -> None:
    from app.auth.models import Profile

    make_profile(db, user_id=TEST_USER_ID, username="first")
    other = make_profile(db, user_id=TEST_USER_ID_2, username="second")
    other.phone_number = hash_phone(RAW)
    db.commit()

    resp = client.patch("/auth/profile", json={"phone_number": PRETTY})
    assert_error(resp, status=400, code="BAD_REQUEST", contains="already linked")
    stored = db.query(Profile).filter(Profile.id == TEST_USER_ID).one().phone_number
    assert stored is None
