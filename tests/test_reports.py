from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.reports.services import create_report
from tests.conftest import CALLER_ID
from tests.factories import make_profile


def test_report_self_rejects_case_insensitive_uuid(client: TestClient) -> None:
    """A differently cased self UUID is still the same reporter."""
    response = client.post(
        "/reports",
        json={"reported_user_id": CALLER_ID.upper(), "reason": "abuse"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "You can't report yourself."


def test_report_dedupes_within_window(db: Session) -> None:
    """A caller cannot flood duplicate reports for the same target."""
    target_id = "22222222-2222-2222-2222-222222222222"
    make_profile(db, user_id=CALLER_ID, username="reporter")
    make_profile(db, user_id=target_id, username="reported")
    first = create_report(CALLER_ID, target_id, "abuse", db)
    second = create_report(CALLER_ID, target_id, "abuse", db)

    assert first["deduped"] is False
    assert second["deduped"] is True
