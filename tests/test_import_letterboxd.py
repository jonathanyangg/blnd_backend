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


ARRIVAL = "https://letterboxd.com/film/arrival/"
DUNE = "https://letterboxd.com/film/dune-2021/"
PARASITE = "https://letterboxd.com/film/parasite-2019/"
MOONLIGHT = "https://letterboxd.com/film/moonlight-2016/"
MATRIX = "https://letterboxd.com/film/the-matrix/"
IGNORED_LIKE = "https://letterboxd.com/film/ignored-like/"
IGNORED_LIST = "https://letterboxd.com/film/ignored-list/"


def _full_letterboxd_export() -> bytes:
    """A complete export: nested folder, all five CSVs, plus likes/ and lists/."""
    root = "letterboxd-demo-2024-06-01/"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            root + "watched.csv",
            "Date,Name,Year,Letterboxd URI,Rating\n"
            "2020-01-01,Arrival,2016," + ARRIVAL + ",2.0\n"
            "2024-05-01,Dune,2021," + DUNE + ",5.0\n"
            "2024-07-01,Heat,1995,https://letterboxd.com/film/heat/,2.0\n",
        )
        archive.writestr(
            root + "ratings.csv",
            "Date,Name,Year,Letterboxd URI,Rating\n"
            "2023-06-01,Arrival,2016," + ARRIVAL + ",4.0\n"
            "2024-01-01,Parasite,2019," + PARASITE + ",4.5\n"
            "2025-01-01,Heat,1995,https://letterboxd.com/film/heat/,3.5\n",
        )
        archive.writestr(
            root + "diary.csv",
            "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date\n"
            "2021-02-01,Arrival,2016," + ARRIVAL + ",3.0,Yes,,2021-02-01\n"
            "2024-08-01,Arrival,2016," + ARRIVAL + ",4.5,Yes,,2024-08-01\n"
            "2022-03-03,Moonlight,2016," + MOONLIGHT + ",5.0,No,,2022-03-03\n",
        )
        archive.writestr(
            root + "reviews.csv",
            "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Review,Tags,Watched Date\n"
            "2022-01-01,Arrival,2016,"
            + ARRIVAL
            + ",1.0,No,Early note,,2022-01-01\n",
        )
        archive.writestr(
            root + "watchlist.csv",
            "Date,Name,Year,Letterboxd URI\n"
            "2024-04-04,The Matrix,1999," + MATRIX + "\n",
        )
        archive.writestr(
            root + "likes/films.csv",
            "Date,Name,Year,Letterboxd URI\n"
            "2024-01-01,Ignored Like,1999," + IGNORED_LIKE + "\n",
        )
        archive.writestr(
            root + "lists/horror.csv",
            "Position,Name,Year,Letterboxd URI\n"
            "1,Ignored List,2000," + IGNORED_LIST + "\n",
        )
        archive.writestr(root + "profile.csv", "Name\nDemo\n")
    return buffer.getvalue()


def test_full_export_merges_latest_rating_and_ignores_extra_files():
    records = _parse_csvs(_full_letterboxd_export())

    assert IGNORED_LIKE not in records
    assert IGNORED_LIST not in records
    assert set(records) == {
        ARRIVAL,
        DUNE,
        PARASITE,
        MOONLIGHT,
        MATRIX,
        "https://letterboxd.com/film/heat/",
    }

    arrival = records[ARRIVAL]
    assert arrival.rating == 4.5
    assert arrival.watched_date.isoformat() == "2024-08-01"
    assert arrival.review == "Early note"
    assert arrival.in_watched is True

    assert records[DUNE].rating == 5.0
    assert records["https://letterboxd.com/film/heat/"].rating == 3.5
    assert records[PARASITE].in_watched is True
    assert records[PARASITE].rating == 4.5
    assert records[MOONLIGHT].in_watched is True
    assert records[MATRIX].in_watchlist is True
    assert records[MATRIX].in_watched is False


class _TitleTMDB:
    def __init__(self) -> None:
        self.ids = {
            "Arrival": 1001,
            "Dune": 1002,
            "Parasite": 1003,
            "Moonlight": 1004,
            "The Matrix": 1005,
            "Heat": 1006,
        }

    async def get(self, url: str, params: dict | None = None) -> _FakeTMDBResponse:
        if url == "/search/movie":
            title = (params or {}).get("query", "")
            tmdb_id = self.ids[title]
            return _FakeTMDBResponse({"results": [{"id": tmdb_id, "title": title}]})
        tmdb_id = int(url.rstrip("/").split("/")[-1])
        return _FakeTMDBResponse(
            {
                "id": tmdb_id,
                "title": "Movie",
                "release_date": "2016-01-01",
                "overview": "Overview",
                "poster_path": "/p.jpg",
                "genres": [{"id": 18, "name": "Drama"}],
                "runtime": 120,
                "vote_average": 8.0,
                "credits": {"cast": [], "crew": []},
                "videos": {"results": []},
            }
        )


def test_full_export_import_saves_latest_ratings(
    client_with_tmdb,
    db: Session,
):
    watchlist = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, watchlist_id=watchlist.id)

    from app.dependencies import get_tmdb_client
    from main import app

    original_override = app.dependency_overrides.get(get_tmdb_client)
    app.dependency_overrides[get_tmdb_client] = lambda: _TitleTMDB()
    try:
        response = client_with_tmdb.post(
            "/import/letterboxd",
            files={
                "file": ("letterboxd.zip", _full_letterboxd_export(), "application/zip")
            },
        )
    finally:
        if original_override is None:
            app.dependency_overrides.pop(get_tmdb_client, None)
        else:
            app.dependency_overrides[get_tmdb_client] = original_override

    assert response.status_code == 200
    summary = response.json()
    assert summary["imported"] == 6
    assert summary["failed"] == 0

    arrival = (
        db.query(WatchedMovie)
        .filter(WatchedMovie.user_id == TEST_USER_ID, WatchedMovie.tmdb_id == 1001)
        .one()
    )
    assert arrival.rating == 4.5
    assert arrival.watched_date.isoformat() == "2024-08-01"
    assert arrival.review == "Early note"

    heat = (
        db.query(WatchedMovie)
        .filter(WatchedMovie.user_id == TEST_USER_ID, WatchedMovie.tmdb_id == 1006)
        .one()
    )
    assert heat.rating == 3.5

    matrix = (
        db.query(WatchlistMovie)
        .filter(
            WatchlistMovie.watchlist_id == watchlist.id,
            WatchlistMovie.tmdb_id == 1005,
        )
        .one()
    )
    assert matrix.source == "letterboxd_import"
    assert (
        db.query(WatchedMovie)
        .filter(WatchedMovie.user_id == TEST_USER_ID, WatchedMovie.tmdb_id == 1005)
        .first()
        is None
    )
