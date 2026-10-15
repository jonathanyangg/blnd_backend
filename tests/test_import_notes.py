"""Tests for the notes import: parse_note_lines + POST /import/notes."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.import_data.workflows import parse_note_lines
from app.tracking.models import WatchlistMovie
from tests.conftest import TEST_USER_ID
from tests.factories import (
    make_movie,
    make_profile,
    make_watchlist,
    make_watchlist_movie,
)

# --- parse_note_lines ---


def _titles(text: str) -> list[str]:
    return [p.title for p in parse_note_lines(text)]


def test_parse_plain_titles() -> None:
    parsed = parse_note_lines("The Godfather\nHeat")
    assert [(p.title, p.year) for p in parsed] == [
        ("The Godfather", None),
        ("Heat", None),
    ]
    assert parsed[0].raw_line == "The Godfather"


def test_parse_bullets_and_numbering() -> None:
    text = "- The Godfather\n* Dune\n• Alien\n· Heat\n1. Se7en\n2) Ronin\n10. Jaws"
    assert _titles(text) == [
        "The Godfather",
        "Dune",
        "Alien",
        "Heat",
        "Se7en",
        "Ronin",
        "Jaws",
    ]


def test_parse_checkboxes() -> None:
    text = "[ ] Dune\n[x] Heat\n- [X] Alien\n☑ Jaws\n✅ Ronin\n☐ Se7en"
    assert _titles(text) == ["Dune", "Heat", "Alien", "Jaws", "Ronin", "Se7en"]


def test_parse_markdown_emphasis() -> None:
    assert _titles("**Dune**\n__Heat__\n*Alien*") == ["Dune", "Heat", "Alien"]


def test_parse_emoji_stripped() -> None:
    assert _titles("🎬 Dune 🍿\nHeat ⭐\n🔥 Alien") == ["Dune", "Heat", "Alien"]


def test_parse_trailing_annotations() -> None:
    text = "Dune — so good\nHeat - rewatch with dad\nAlien – classic"
    assert _titles(text) == ["Dune", "Heat", "Alien"]


def test_parse_watched_markers() -> None:
    text = "Dune (watched)\nHeat (seen)\nAlien watched\nRonin seen"
    assert _titles(text) == ["Dune", "Heat", "Alien", "Ronin"]


def test_parse_paren_year() -> None:
    parsed = parse_note_lines("The Matrix (1999)")
    assert parsed[0].title == "The Matrix"
    assert parsed[0].year == 1999


def test_parse_bare_trailing_year() -> None:
    parsed = parse_note_lines("The Matrix 1999\nThe Thing, 1982")
    assert [(p.title, p.year) for p in parsed] == [
        ("The Matrix", 1999),
        ("The Thing", 1982),
    ]


def test_parse_year_like_titles_kept() -> None:
    """A title that IS a year, or ends in a far-future year, is not split."""
    parsed = parse_note_lines("1917\nBlade Runner 2049\n2001: A Space Odyssey")
    assert [(p.title, p.year) for p in parsed] == [
        ("1917", None),
        ("Blade Runner 2049", None),
        ("2001: A Space Odyssey", None),
    ]


def test_parse_drops_headers_and_empty_lines() -> None:
    text = "To watch:\n\nMovies:\n   \nDune\n# Best of 2024:"
    assert _titles(text) == ["Dune"]


def test_parse_drops_prose_lines() -> None:
    prose = (
        "I was thinking we could all get together next weekend and have a big "
        "movie marathon at my place"
    )
    assert _titles(f"{prose}\nDune") == ["Dune"]


def test_parse_combined_formatting() -> None:
    parsed = parse_note_lines("- [x] **The Matrix** (1999) ✅ — mind-blowing")
    assert [(p.title, p.year) for p in parsed] == [("The Matrix", 1999)]
    assert parsed[0].raw_line == "- [x] **The Matrix** (1999) ✅ — mind-blowing"


def test_parse_empty_input() -> None:
    assert parse_note_lines("") == []
    assert parse_note_lines("\n\n   \n") == []


# --- POST /import/notes ---


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


# title (lowercased search query) -> (tmdb_id, title, release_date)
_CATALOG = {
    "the godfather": (238, "The Godfather", "1972-03-14"),
    "dune": (438631, "Dune", "2021-09-15"),
    "fight club": (550, "Fight Club", "1999-10-15"),
}


class _FakeNotesTMDBClient:
    """Fake TMDB client: search resolves from _CATALOG; details returns a movie."""

    async def get(self, url: str, params: dict | None = None) -> _FakeResponse:
        if url == "/search/movie":
            entry = _CATALOG.get((params or {})["query"].lower())
            results = (
                [{"id": entry[0], "title": entry[1], "release_date": entry[2]}]
                if entry
                else []
            )
            return _FakeResponse({"results": results})

        tmdb_id = int(url.rstrip("/").split("/")[-1])
        for cat_id, title, release_date in _CATALOG.values():
            if cat_id == tmdb_id:
                return _FakeResponse(
                    {
                        "id": cat_id,
                        "title": title,
                        "release_date": release_date,
                        "overview": "An overview.",
                        "poster_path": f"/poster-{cat_id}.jpg",
                        "genres": [],
                        "runtime": 120,
                        "vote_average": 8.0,
                        "credits": {"cast": [], "crew": []},
                        "videos": {"results": []},
                    }
                )
        raise AssertionError(f"Unexpected TMDB details request for {tmdb_id}")


@pytest.fixture
def notes_client(db: Session) -> Generator[TestClient, None, None]:
    """TestClient with a catalog-backed fake TMDB client (search + details)."""
    from app.dependencies import get_current_user, get_db, get_tmdb_client
    from main import app

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
    app.dependency_overrides[get_tmdb_client] = lambda: _FakeNotesTMDBClient()

    test_client = TestClient(app)
    yield test_client

    for dep in (get_db, get_current_user, get_tmdb_client):
        app.dependency_overrides.pop(dep, None)


def test_import_notes_returns_candidates_without_writing(
    notes_client: TestClient, db: Session
) -> None:
    wl = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="user1", watchlist_id=wl.id)

    text = (
        "My movies to watch:\n"
        "- [x] The Godfather (1972) ⭐\n"
        "1. **Dune** — heard it's great\n"
        "Some totally unknown movie\n"
    )
    resp = notes_client.post("/import/notes", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    assert data["truncated"] is False
    assert len(data["lines"]) == 3
    godfather = data["lines"][0]
    assert godfather["title"] == "The Godfather"
    assert godfather["year"] == 1972
    assert godfather["candidates"][0]["tmdb_id"] == 238
    assert godfather["candidates"][0]["confidence"] >= 0.9
    assert data["lines"][1]["candidates"][0]["tmdb_id"] == 438631
    assert data["lines"][2]["candidates"] == []
    assert (
        db.query(WatchlistMovie).filter(WatchlistMovie.watchlist_id == wl.id).count()
        == 0
    )


def test_confirm_notes_adds_to_watchlist(notes_client: TestClient, db: Session) -> None:
    wl = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="user1", watchlist_id=wl.id)
    resp = notes_client.post(
        "/import/notes/confirm",
        json={
            "items": [
                {"tmdb_id": 238, "media_type": "movie", "destination": "watchlist"},
                {
                    "tmdb_id": 438631,
                    "media_type": "movie",
                    "destination": "watched",
                    "rating": 4.5,
                },
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json()["added"] == 2
    assert resp.json()["failed"] == []
    saved = db.query(WatchlistMovie).filter(WatchlistMovie.watchlist_id == wl.id).one()
    assert saved.tmdb_id == 238
    assert saved.source == "notes_import"


def test_confirm_notes_skips_duplicate_watchlist(
    notes_client: TestClient, db: Session
) -> None:
    wl = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="user1", watchlist_id=wl.id)
    make_movie(db, tmdb_id=940550, title="Fight Club", poster_path="/poster.jpg")
    make_watchlist_movie(db, watchlist_id=wl.id, tmdb_id=940550)
    resp = notes_client.post(
        "/import/notes/confirm",
        json={"items": [{"tmdb_id": 940550, "destination": "watchlist"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["added"] == 0
    assert resp.json()["skipped"] == 1


def test_import_notes_text_too_long(notes_client: TestClient) -> None:
    resp = notes_client.post("/import/notes", json={"text": "a" * 20_001})
    assert resp.status_code == 422


def test_import_notes_only_headers(notes_client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    resp = notes_client.post("/import/notes", json={"text": "To watch:\n\n"})
    assert resp.status_code == 200
    assert resp.json() == {"lines": [], "truncated": False}


def test_import_notes_truncates_at_cap(notes_client: TestClient) -> None:
    text = "\n".join(f"Unknown Movie {i}" for i in range(101))
    resp = notes_client.post("/import/notes", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    assert data["truncated"] is True
    assert len(data["lines"]) == 100
