import io
import zipfile

from sqlalchemy.orm import Session

from app.tracking.models import WatchedMovie, WatchlistMovie
from app.import_data.workflows import _parse_csvs
from tests.conftest import TEST_USER_ID
from tests.factories import make_profile, make_watchlist


class _FakeTMDBResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _FakeTMDBClient:
    def __init__(self, details: dict) -> None:
        self.details = details

    async def get(self, url: str, params: dict | None = None) -> _FakeTMDBResponse:
        if url == "/search/movie":
            return _FakeTMDBResponse({"results": [{"id": 550, "title": "Fight Club"}]})
        return _FakeTMDBResponse(self.details)


def _letterboxd_export() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "watched.csv",
            "Date,Name,Year,Letterboxd URI,Rating\n"
            "2024-01-01,Fight Club,1999,https://letterboxd.com/film/fight-club/,4.5\n",
        )
        archive.writestr(
            "watchlist.csv",
            "Date,Name,Year,Letterboxd URI\n"
            "2024-01-02,Fight Club,1999,https://letterboxd.com/film/fight-club/\n",
        )
    return buffer.getvalue()


def test_letterboxd_export_parses_watched_watchlist_and_rating():
    records = _parse_csvs(_letterboxd_export())

    assert set(records) == {"https://letterboxd.com/film/fight-club/"}
    record = records["https://letterboxd.com/film/fight-club/"]
    assert record.name == "Fight Club"
    assert record.year == 1999
    assert record.rating == 4.5
    assert record.in_watched is True
    assert record.in_watchlist is True


def test_letterboxd_import_creates_watched_and_watchlist_entries(
    client_with_tmdb,
    db: Session,
):
    watchlist = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, watchlist_id=watchlist.id)
    details = {
        "id": 550,
        "title": "Fight Club",
        "release_date": "1999-10-15",
        "overview": "An insomniac office worker...",
        "poster_path": "/poster.jpg",
        "genres": [{"id": 18, "name": "Drama"}],
        "runtime": 139,
        "vote_average": 8.4,
        "credits": {"cast": [], "crew": []},
        "videos": {"results": []},
    }

    from app.dependencies import get_tmdb_client
    from main import app

    original_override = app.dependency_overrides.get(get_tmdb_client)
    app.dependency_overrides[get_tmdb_client] = lambda: _FakeTMDBClient(details)
    try:
        response = client_with_tmdb.post(
            "/import/letterboxd",
            files={"file": ("export.zip", _letterboxd_export(), "application/zip")},
        )
    finally:
        if original_override is None:
            app.dependency_overrides.pop(get_tmdb_client, None)
        else:
            app.dependency_overrides[get_tmdb_client] = original_override

    assert response.status_code == 200
    summary = response.json()
    assert summary["imported"] == 2
    assert summary["skipped"] == 0
    assert summary["failed"] == 0

    watched = (
        db.query(WatchedMovie)
        .filter(
            WatchedMovie.user_id == TEST_USER_ID,
            WatchedMovie.tmdb_id == 550,
        )
        .one()
    )
    assert watched.rating == 4.5
    assert watched.source == "letterboxd_import"

    watchlisted = (
        db.query(WatchlistMovie)
        .filter(
            WatchlistMovie.watchlist_id == watchlist.id,
            WatchlistMovie.tmdb_id == 550,
        )
        .one()
    )
    assert watchlisted.source == "letterboxd_import"
