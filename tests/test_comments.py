from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from tests.conftest import CALLER_ID, TARGET_ID  # noqa: F401


def _make_comment_mock(
    comment_id: int = 1,
    tmdb_id: int = 550,
    user_id: str = CALLER_ID,
    parent_id: int | None = None,
    body: str = "Great movie!",
    is_edited: bool = False,
    deleted: bool = False,
) -> MagicMock:
    m = MagicMock()
    m.id = comment_id
    m.tmdb_id = tmdb_id
    m.user_id = user_id
    m.parent_id = parent_id
    m.body = body
    m.is_edited = is_edited
    m.deleted = deleted
    m.created_at = datetime(2026, 4, 23, tzinfo=timezone.utc)
    m.updated_at = datetime(2026, 4, 23, tzinfo=timezone.utc)
    return m


def _make_profile_mock(user_id: str = CALLER_ID) -> MagicMock:
    m = MagicMock()
    m.id = user_id
    m.username = "testuser"
    m.avatar_url = "https://example.com/avatar.jpg"
    return m


def _comment_dict(
    comment_id: int = 1,
    tmdb_id: int = 550,
    parent_id: int | None = None,
    body: str = "Great movie!",
    is_edited: bool = False,
) -> dict:
    return {
        "id": comment_id,
        "tmdb_id": tmdb_id,
        "parent_id": parent_id,
        "user_id": CALLER_ID,
        "username": "testuser",
        "avatar_url": "https://example.com/avatar.jpg",
        "body": body,
        "like_count": 0,
        "liked_by_me": False,
        "commenter_rating": None,
        "is_edited": is_edited,
        "created_at": "2026-04-23T00:00:00Z",
        "replies": [],
    }


@patch("app.comments.views.services.create_comment")
def test_create_comment(
    mock_create: MagicMock, app_client: MagicMock, mock_db: MagicMock
) -> None:
    """POST /comments/ creates a top-level comment and returns 201."""
    mock_create.return_value = _comment_dict()

    response = app_client.post(
        "/comments/", json={"tmdb_id": 550, "body": "Great movie!"}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["id"] == 1
    assert data["body"] == "Great movie!"
    assert data["tmdb_id"] == 550
    mock_create.assert_called_once()


def test_create_comment_body_too_long(
    app_client: MagicMock, mock_db: MagicMock
) -> None:
    """POST /comments/ with 1001-char body returns 422."""
    response = app_client.post("/comments/", json={"tmdb_id": 550, "body": "x" * 1001})
    assert response.status_code == 422


def test_create_comment_empty_body(app_client: MagicMock, mock_db: MagicMock) -> None:
    """POST /comments/ with empty body returns 422."""
    response = app_client.post("/comments/", json={"tmdb_id": 550, "body": ""})
    assert response.status_code == 422


@patch("app.comments.views.services.get_comments")
def test_list_comments(
    mock_get: MagicMock, app_client: MagicMock, mock_db: MagicMock
) -> None:
    """GET /comments/?tmdb_id=550 returns 200 with results and total."""
    mock_get.return_value = {"results": [_comment_dict()], "total": 1}

    response = app_client.get("/comments/?tmdb_id=550")

    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "total" in data
    assert data["total"] == 1
    assert len(data["results"]) == 1
    mock_get.assert_called_once()


@patch("app.comments.views.services.create_reply")
def test_create_reply(
    mock_reply: MagicMock, app_client: MagicMock, mock_db: MagicMock
) -> None:
    """POST /comments/1/reply returns 201 with parent_id=1."""
    mock_reply.return_value = _comment_dict(comment_id=2, parent_id=1, body="I agree!")

    response = app_client.post("/comments/1/reply", json={"body": "I agree!"})

    assert response.status_code == 201
    data = response.json()
    assert data["parent_id"] == 1
    mock_reply.assert_called_once()


@patch("app.comments.views.services.create_reply")
def test_reply_to_reply_returns_400(
    mock_reply: MagicMock, app_client: MagicMock, mock_db: MagicMock
) -> None:
    """POST /comments/2/reply returns 400 when replying to a reply."""
    mock_reply.side_effect = HTTPException(
        status_code=400, detail="Cannot reply to a reply"
    )

    response = app_client.post("/comments/2/reply", json={"body": "Nested"})

    assert response.status_code == 400


@patch("app.comments.views.services.edit_comment")
def test_edit_comment(
    mock_edit: MagicMock, app_client: MagicMock, mock_db: MagicMock
) -> None:
    """PATCH /comments/1 returns 200 with updated body and is_edited=True."""
    mock_edit.return_value = _comment_dict(body="Updated text", is_edited=True)

    response = app_client.patch("/comments/1", json={"body": "Updated text"})

    assert response.status_code == 200
    data = response.json()
    assert data["body"] == "Updated text"
    assert data["is_edited"] is True
    mock_edit.assert_called_once()


@patch("app.comments.views.services.edit_comment")
def test_edit_comment_forbidden(
    mock_edit: MagicMock, app_client: MagicMock, mock_db: MagicMock
) -> None:
    """PATCH /comments/1 returns 403 when user is not the owner."""
    mock_edit.side_effect = HTTPException(
        status_code=403, detail="Not authorized or comment not found"
    )

    response = app_client.patch("/comments/1", json={"body": "hack"})

    assert response.status_code == 403


@patch("app.comments.views.services.delete_comment")
def test_soft_delete_comment(
    mock_delete: MagicMock, app_client: MagicMock, mock_db: MagicMock
) -> None:
    """DELETE /comments/1 returns 204 on success."""
    mock_delete.return_value = None

    response = app_client.delete("/comments/1")

    assert response.status_code == 204
    mock_delete.assert_called_once()


@patch("app.comments.views.services.delete_comment")
def test_delete_comment_forbidden(
    mock_delete: MagicMock, app_client: MagicMock, mock_db: MagicMock
) -> None:
    """DELETE /comments/1 returns 403 when user is not the owner."""
    mock_delete.side_effect = HTTPException(
        status_code=403, detail="Not authorized or comment not found"
    )

    response = app_client.delete("/comments/1")

    assert response.status_code == 403


@patch("app.comments.views.services.like_comment")
def test_like_comment(
    mock_like: MagicMock, app_client: MagicMock, mock_db: MagicMock
) -> None:
    """POST /comments/1/like returns 200 with updated like_count and liked_by_me=True."""
    mock_like.return_value = {"like_count": 1, "liked_by_me": True}

    response = app_client.post("/comments/1/like")

    assert response.status_code == 200
    data = response.json()
    assert data["like_count"] == 1
    assert data["liked_by_me"] is True
    mock_like.assert_called_once()


@patch("app.comments.views.services.like_comment")
def test_like_comment_duplicate(
    mock_like: MagicMock, app_client: MagicMock, mock_db: MagicMock
) -> None:
    """POST /comments/1/like returns 400 when already liked."""
    mock_like.side_effect = HTTPException(status_code=400, detail="Already liked")

    response = app_client.post("/comments/1/like")

    assert response.status_code == 400


@patch("app.comments.views.services.unlike_comment")
def test_unlike_comment(
    mock_unlike: MagicMock, app_client: MagicMock, mock_db: MagicMock
) -> None:
    """DELETE /comments/1/like returns 200 with like_count=0 and liked_by_me=False."""
    mock_unlike.return_value = {"like_count": 0, "liked_by_me": False}

    response = app_client.delete("/comments/1/like")

    assert response.status_code == 200
    data = response.json()
    assert data["like_count"] == 0
    assert data["liked_by_me"] is False
    mock_unlike.assert_called_once()


@patch("app.comments.views.services.unlike_comment")
def test_unlike_comment_not_found(
    mock_unlike: MagicMock, app_client: MagicMock, mock_db: MagicMock
) -> None:
    """DELETE /comments/1/like returns 404 when like not found."""
    mock_unlike.side_effect = HTTPException(status_code=404, detail="Like not found")

    response = app_client.delete("/comments/1/like")

    assert response.status_code == 404
