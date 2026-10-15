"""Affiliate adapters, streaming where-to-watch, and click redirects."""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.affiliate.models import AffiliateClick, WatchProviderCache
from app.affiliate.providers import (
    AMAZON,
    APPLE,
    CJ,
    IMPACT,
    PASSTHROUGH,
    RAKUTEN,
    REGISTRY,
    TARGETS,
    AffiliateProvider,
    Offer,
    Provider,
    Title,
    links_for,
    outbound_url,
    resolve_amazon_tag,
)
from app.config import settings
from app.movies.schemas import MovieResponse
from app.streaming.schemas import (
    StreamingAvailabilityResponse,
    StreamingOption,
    StreamingServiceInfo,
)
from tests.conftest import TEST_USER_ID
from tests.factories import make_movie, make_profile

TITLE = Title("Fight Club", 1999, "movie", 550)
PRIME = Offer(119, "Amazon Prime Video", "flatrate")
AMAZON_VIDEO = Offer(10, "Amazon Video", "rent")
REGION_LINK = "https://www.themoviedb.org/movie/550/watch?locale=US"


def _offer(provider_id: int, name: str = "Provider") -> Offer:
    return Offer(provider_id, name, "flatrate")


class _Resp:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> dict:
        return self._payload


WATCH = {
    "id": 550,
    "results": {
        "US": {
            "link": REGION_LINK,
            "flatrate": [
                {
                    "logo_path": "/prime.jpg",
                    "provider_id": 119,
                    "provider_name": "Amazon Prime Video",
                    "display_priority": 1,
                },
                {
                    "logo_path": "/netflix.jpg",
                    "provider_id": 8,
                    "provider_name": "Netflix",
                    "display_priority": 2,
                },
            ],
            "rent": [
                {
                    "logo_path": "/amz.jpg",
                    "provider_id": 10,
                    "provider_name": "Amazon Video",
                    "display_priority": 3,
                }
            ],
            "buy": [
                {
                    "logo_path": "/apple.jpg",
                    "provider_id": 2,
                    "provider_name": "Apple TV",
                    "display_priority": 4,
                }
            ],
        },
        "DE": {
            "link": "https://www.themoviedb.org/movie/550/watch?locale=DE",
            "flatrate": [],
            "rent": [],
            "buy": [],
        },
    },
}

TV_WATCH = {
    "id": 1399,
    "results": {
        "US": {
            "link": "https://www.themoviedb.org/tv/1399/watch?locale=US",
            "flatrate": [
                {
                    "logo_path": "/prime.jpg",
                    "provider_id": 119,
                    "provider_name": "Amazon Prime Video",
                }
            ],
            "rent": [],
            "buy": [],
        }
    },
}


class FakeTMDB:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_watch = False
        self.fail_title = False

    async def get(self, url: str, params: dict | None = None) -> _Resp:
        self.calls.append(url)
        if url.endswith("/watch/providers"):
            if self.fail_watch:
                return _Resp({}, status=503)
            if "/tv/" in url:
                return _Resp(TV_WATCH)
            return _Resp(WATCH)
        if self.fail_title:
            return _Resp({}, status=404)
        if url.startswith("/tv/"):
            return _Resp(
                {
                    "id": 1399,
                    "name": "Game of Thrones",
                    "first_air_date": "2011-04-17",
                    "overview": "Nine noble families...",
                    "poster_path": "/tv-poster.jpg",
                    "genres": [],
                    "episode_run_time": [57],
                    "vote_average": 8.4,
                }
            )
        return _Resp(
            {
                "id": 550,
                "title": "Fight Club",
                "release_date": "1999-10-15",
                "overview": "An insomniac office worker...",
                "genres": [],
                "credits": {"cast": [], "crew": []},
                "videos": {"results": []},
            }
        )


class FakeStreaming:
    async def get(self, url: str, params: dict | None = None) -> _Resp:
        country = (params or {}).get("country", "us")
        return _Resp(
            {
                "streamingOptions": {
                    country: [
                        {
                            "service": {
                                "id": "prime",
                                "name": "Prime Video",
                                "imageSet": {
                                    "darkThemeImage": "https://img.example/prime.png"
                                },
                            },
                            "type": "subscription",
                            "link": "https://www.primevideo.com/detail/example",
                            "quality": "hd",
                            "expiresSoon": False,
                        }
                    ]
                }
            }
        )


@pytest.fixture
def with_tmdb(client: TestClient):
    """Redirect and TV routes depend on the TMDB client even when they 404."""
    from app.dependencies import get_tmdb_client
    from main import app

    fake = FakeTMDB()
    app.dependency_overrides[get_tmdb_client] = lambda: fake
    yield client, fake
    app.dependency_overrides.pop(get_tmdb_client, None)


@pytest.fixture
def streaming_api(client: TestClient):
    from app.dependencies import get_streaming_client, get_tmdb_client
    from main import app

    fake_tmdb = FakeTMDB()
    app.dependency_overrides[get_tmdb_client] = lambda: fake_tmdb
    app.dependency_overrides[get_streaming_client] = lambda: FakeStreaming()
    yield client, fake_tmdb
    app.dependency_overrides.pop(get_tmdb_client, None)
    app.dependency_overrides.pop(get_streaming_client, None)


def test_streaming_option_shape_is_unchanged() -> None:
    option = StreamingOption(
        service=StreamingServiceInfo(id="prime", name="Prime Video"),
        type="subscription",
        link="https://www.primevideo.com/detail/example",
    )
    assert set(option.model_dump()) == {
        "service",
        "type",
        "link",
        "quality",
        "price",
        "expires_soon",
    }
    response = StreamingAvailabilityResponse(tmdb_id=1, country="us", options=[])
    assert response.where_to_watch is None
    assert "where_to_watch" not in MovieResponse.model_fields
    assert "options" in StreamingAvailabilityResponse.model_fields


def test_resolve_amazon_tag() -> None:
    assert resolve_amazon_tag(None) == "blndmovies-20"
    assert resolve_amazon_tag("") is None
    assert resolve_amazon_tag("  ") is None
    assert resolve_amazon_tag("custom-20") == "custom-20"


def test_amazon_default_tag_and_urls() -> None:
    assert settings.amazon_associates_tag is None
    prime = AMAZON.build_web_url(TITLE, PRIME)
    video = AMAZON.build_web_url(TITLE, AMAZON_VIDEO)
    assert prime.startswith("https://www.amazon.com/gp/video/search?phrase=")
    assert "Fight%20Club%201999" in prime
    assert "tag=blndmovies-20" in prime
    assert video.startswith("https://www.amazon.com/s?k=")
    assert "i=instant-video" in video
    assert "tag=blndmovies-20" in video
    app = AMAZON.build_app_deeplink(TITLE, PRIME)
    assert app == "aiv://aiv/search?phrase=Fight%20Club%201999"


def test_amazon_custom_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "amazon_associates_tag", "custom-20")
    assert "tag=custom-20" in AMAZON.build_web_url(TITLE, PRIME)


def test_amazon_empty_tag_is_untagged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "amazon_associates_tag", "")
    url = AMAZON.build_web_url(TITLE, PRIME)
    assert "tag=" not in url
    assert "blndmovies-20" not in url
    assert AMAZON.supports(TITLE, Provider(119, "Amazon Prime Video")) is True


def test_amazon_disabled_uses_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "amazon_associates_enabled", False)
    assert AMAZON.supports(TITLE, Provider(119, "Amazon Prime Video")) is False
    web, app = links_for(TITLE, PRIME)
    assert web.startswith("https://www.amazon.com/gp/video/search?phrase=")
    assert "tag=" not in web
    assert app is None


@pytest.mark.parametrize(
    ("adapter", "provider_id", "host", "param", "enabled_attr", "partner_attr"),
    [
        (
            IMPACT,
            531,
            "www.paramountplus.com",
            "subId1",
            "impact_enabled",
            "impact_partner_id",
        ),
        (
            IMPACT,
            386,
            "www.peacocktv.com",
            "subId1",
            "impact_enabled",
            "impact_partner_id",
        ),
        (
            IMPACT,
            387,
            "www.peacocktv.com",
            "subId1",
            "impact_enabled",
            "impact_partner_id",
        ),
        (
            RAKUTEN,
            15,
            "www.hulu.com",
            "ranSiteID",
            "rakuten_enabled",
            "rakuten_partner_id",
        ),
        (CJ, 43, "www.starz.com", "sid", "cj_enabled", "cj_partner_id"),
        (CJ, 283, "www.crunchyroll.com", "sid", "cj_enabled", "cj_partner_id"),
        (
            APPLE,
            2,
            "tv.apple.com",
            "at",
            "apple_tv_affiliate_enabled",
            "apple_tv_affiliate_token",
        ),
        (
            APPLE,
            350,
            "tv.apple.com",
            "at",
            "apple_tv_affiliate_enabled",
            "apple_tv_affiliate_token",
        ),
    ],
)
def test_stub_tags_search_url_only_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    adapter: AffiliateProvider,
    provider_id: int,
    host: str,
    param: str,
    enabled_attr: str,
    partner_attr: str,
) -> None:
    offer = _offer(provider_id)
    provider = Provider(provider_id, "Provider")
    assert adapter.supports(TITLE, provider) is False
    web, app = links_for(TITLE, offer)
    assert web.startswith(f"https://{host}/")
    assert param not in web
    assert app is None

    monkeypatch.setattr(settings, enabled_attr, True)
    monkeypatch.setattr(settings, partner_attr, "partner 1")
    assert adapter.supports(TITLE, provider) is True
    tagged = adapter.build_web_url(TITLE, offer)
    assert tagged.startswith(f"https://{host}/")
    assert f"{param}=partner%201" in tagged
    assert adapter.build_app_deeplink(TITLE, offer) is None


def test_partner_id_cannot_inject_query_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "impact_enabled", True)
    monkeypatch.setattr(settings, "impact_partner_id", "ok&url=https://evil.example")
    url = IMPACT.build_web_url(TITLE, _offer(531, "Paramount Plus"))
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.hostname == "www.paramountplus.com"
    assert "url" not in query
    assert query["subId1"] == ["ok&url=https://evil.example"]


def test_passthrough_unknown_provider_uses_region_link() -> None:
    offer = Offer(8, "Netflix", "flatrate", region_link=REGION_LINK)
    assert PASSTHROUGH.build_web_url(TITLE, offer) == REGION_LINK
    assert PASSTHROUGH.build_app_deeplink(TITLE, offer) is None
    web, app = links_for(TITLE, offer)
    assert web == REGION_LINK
    assert app is None


def test_passthrough_known_provider_is_untagged_search() -> None:
    web = PASSTHROUGH.build_web_url(TITLE, _offer(15, "Hulu"))
    assert web.startswith("https://www.hulu.com/search?q=Fight%20Club%201999")
    assert "ranSiteID" not in web


def test_registry_is_the_tmdb_provider_allow_list() -> None:
    assert set(REGISTRY) == set(TARGETS)
    assert REGISTRY[119] is AMAZON
    assert REGISTRY[10] is AMAZON
    assert REGISTRY[531] is IMPACT
    assert REGISTRY[386] is IMPACT
    assert REGISTRY[387] is IMPACT
    assert REGISTRY[15] is RAKUTEN
    assert REGISTRY[43] is CJ
    assert REGISTRY[283] is CJ
    assert REGISTRY[2] is APPLE
    assert REGISTRY[350] is APPLE
    assert 8 not in REGISTRY


def test_outbound_url_rejects_foreign_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.affiliate.providers.links_for",
        lambda title, offer: ("https://evil.example/steal", None),
    )
    with pytest.raises(ValueError):
        outbound_url(TITLE, 119)


def test_movie_streaming_keeps_options_and_adds_watch_links(
    streaming_api, db: Session
) -> None:
    client, fake_tmdb = streaming_api
    make_movie(db)

    first = client.get("/movies/550/streaming")
    second = client.get("/movies/550/streaming")
    germany = client.get("/movies/550/streaming", params={"country": "de"})

    assert first.status_code == 200
    body = first.json()
    assert body["country"] == "us"
    assert body["options"][0]["link"] == "https://www.primevideo.com/detail/example"
    assert body["options"][0]["service"]["id"] == "prime"
    assert body["options"][0]["type"] == "subscription"
    watch = body["where_to_watch"]
    assert watch["attribution"] == "Data provided by JustWatch"
    assert watch["link"] == REGION_LINK
    assert watch["country"] == "US"
    prime = watch["flatrate"][0]
    assert prime["provider_id"] == 119
    assert prime["web_url"].startswith("https://www.amazon.com/gp/video/search?phrase=")
    assert "tag=blndmovies-20" in prime["web_url"]
    assert prime["app_url"] == "aiv://aiv/search?phrase=Fight%20Club%201999"
    netflix = watch["flatrate"][1]
    assert netflix["provider_id"] == 8
    assert netflix["web_url"] == REGION_LINK
    assert netflix["app_url"] is None
    assert "tag=blndmovies-20" in watch["rent"][0]["web_url"]
    assert "i=instant-video" in watch["rent"][0]["web_url"]
    assert watch["buy"][0]["web_url"].startswith("https://tv.apple.com/")
    assert "at=" not in watch["buy"][0]["web_url"]
    assert watch["buy"][0]["app_url"] is None

    assert second.json()["where_to_watch"]["flatrate"][0]["provider_id"] == 119
    assert germany.json()["where_to_watch"]["country"] == "DE"
    assert germany.json()["where_to_watch"]["flatrate"] == []
    assert germany.json()["options"][0]["link"] == (
        "https://www.primevideo.com/detail/example"
    )
    assert fake_tmdb.calls == ["/movie/550/watch/providers"]


def test_watch_provider_failure_does_not_drop_streaming_options(
    streaming_api, db: Session
) -> None:
    client, fake_tmdb = streaming_api
    make_movie(db)
    fake_tmdb.fail_watch = True

    response = client.get("/movies/550/streaming")

    assert response.status_code == 200
    body = response.json()
    assert body["options"][0]["link"] == "https://www.primevideo.com/detail/example"
    assert body["where_to_watch"] is None


def test_stale_watch_cache_is_used_when_tmdb_fails(streaming_api, db: Session) -> None:
    client, fake_tmdb = streaming_api
    make_movie(db)
    assert client.get("/movies/550/streaming").status_code == 200
    row = db.query(WatchProviderCache).one()
    row.fetched_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.commit()
    fake_tmdb.fail_watch = True

    response = client.get("/movies/550/streaming")

    assert response.status_code == 200
    assert (
        "tag=blndmovies-20"
        in response.json()["where_to_watch"]["flatrate"][0]["web_url"]
    )


def test_missing_title_falls_back_to_justwatch_link(
    streaming_api, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _fake_tmdb = streaming_api
    make_movie(db)

    def missing(*_args, **_kwargs):
        request = httpx.Request("GET", "https://api.themoviedb.org/3/movie/550")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("missing", request=request, response=response)

    monkeypatch.setattr("app.affiliate.services.load_title", missing)

    response = client.get("/movies/550/streaming")

    assert response.status_code == 200
    watch = response.json()["where_to_watch"]
    assert watch["flatrate"][0]["web_url"] == REGION_LINK
    assert watch["flatrate"][0]["app_url"] is None
    assert response.json()["options"][0]["service"]["id"] == "prime"


def test_streaming_options_survive_watch_builder_bug(
    streaming_api, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _fake = streaming_api
    make_movie(db)

    def boom(*_args, **_kwargs):
        raise RuntimeError("link builder broke")

    monkeypatch.setattr("app.affiliate.services.get_where_to_watch", boom)
    response = client.get("/movies/550/streaming")

    assert response.status_code == 200
    assert response.json()["options"][0]["type"] == "subscription"
    assert response.json()["where_to_watch"] is None


def test_tv_streaming_is_disabled_by_default(with_tmdb) -> None:
    client, _fake = with_tmdb
    response = client.get("/tv/1399/streaming")
    assert response.status_code == 404


def test_tv_streaming_uses_same_shape(
    streaming_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, fake_tmdb = streaming_api
    monkeypatch.setattr(settings, "tv_support_enabled", True)

    response = client.get("/tv/1399/streaming")

    assert response.status_code == 200
    body = response.json()
    assert body["options"] == []
    assert body["where_to_watch"]["attribution"] == "Data provided by JustWatch"
    prime = body["where_to_watch"]["flatrate"][0]
    assert "Game%20of%20Thrones%202011" in prime["web_url"]
    assert "tag=blndmovies-20" in prime["web_url"]
    assert "/tv/1399/watch/providers" in fake_tmdb.calls
    assert "/tv/1399" in fake_tmdb.calls


def _seed_redirect(db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID)
    make_movie(db)


def test_redirect_logs_click_before_302(
    with_tmdb, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _fake = with_tmdb
    _seed_redirect(db)
    seen: list[int] = []
    real = RedirectResponse

    def spy(url: str, status_code: int = 307):
        row = db.query(AffiliateClick).one()
        assert str(row.user_id) == TEST_USER_ID
        assert row.media_type == "movie"
        assert row.tmdb_id == 550
        assert row.provider == 119
        assert row.created_at is not None
        seen.append(row.id)
        return real(url, status_code=status_code)

    monkeypatch.setattr("app.affiliate.views.RedirectResponse", spy)
    response = client.get(
        "/out/119/movie/550",
        params={"url": "https://evil.example"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    assert urlparse(location).hostname == "www.amazon.com"
    assert "tag=blndmovies-20" in location
    assert "Fight%20Club%201999" in location
    assert "evil.example" not in location
    assert seen == [db.query(AffiliateClick).one().id]


def test_failed_click_log_does_not_redirect(
    with_tmdb, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _fake = with_tmdb
    _seed_redirect(db)
    built: list[str] = []

    def boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.affiliate.views.log_click", boom)
    monkeypatch.setattr(
        "app.affiliate.views.RedirectResponse",
        lambda url, status_code=307: built.append(url),
    )

    with pytest.raises(RuntimeError, match="db down"):
        client.get("/out/119/movie/550", follow_redirects=False)

    assert built == []
    assert db.query(AffiliateClick).count() == 0


def test_unknown_provider_is_not_a_redirect(with_tmdb, db: Session) -> None:
    client, _fake = with_tmdb
    response = client.get("/out/8/movie/550", follow_redirects=False)
    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown provider"
    assert "location" not in response.headers
    assert db.query(AffiliateClick).count() == 0


def test_redirect_rejects_foreign_host_without_click(
    with_tmdb, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _fake = with_tmdb
    _seed_redirect(db)

    def refuse(*_args, **_kwargs):
        raise ValueError("evil.example")

    monkeypatch.setattr("app.affiliate.views.outbound_url", refuse)
    response = client.get("/out/119/movie/550", follow_redirects=False)

    assert response.status_code == 400
    assert response.json()["detail"] == "Refusing redirect"
    assert db.query(AffiliateClick).count() == 0


def test_redirect_rejects_bad_media_type(with_tmdb, db: Session) -> None:
    client, _fake = with_tmdb
    response = client.get("/out/119/podcast/550", follow_redirects=False)
    assert response.status_code == 404
    assert db.query(AffiliateClick).count() == 0


def test_tv_redirect_is_disabled_by_default(with_tmdb, db: Session) -> None:
    client, _fake = with_tmdb
    response = client.get("/out/119/tv/1399", follow_redirects=False)
    assert response.status_code == 404
    assert db.query(AffiliateClick).count() == 0


def test_tv_redirect_uses_show_title(
    with_tmdb, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _fake = with_tmdb
    make_profile(db, user_id=TEST_USER_ID, username="tvredirect")
    db.execute(
        text(
            "INSERT INTO tv_shows (tmdb_id, title, first_air_year) "
            "VALUES (1399, 'Game of Thrones', 2011)"
        )
    )
    db.commit()
    monkeypatch.setattr(settings, "tv_support_enabled", True)

    response = client.get("/out/119/tv/1399", follow_redirects=False)

    assert response.status_code == 302
    assert "Game%20of%20Thrones%202011" in response.headers["location"]
    row = db.query(AffiliateClick).one()
    assert row.media_type == "tv"
    assert row.tmdb_id == 1399
    assert row.provider == 119


def test_affiliate_clicks_rls(db: Session) -> None:
    rel = db.execute(
        text(
            "select c.relrowsecurity from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relname = 'affiliate_clicks'"
        )
    ).scalar_one()
    assert rel is True
    policies = db.execute(
        text(
            "select polname from pg_policy "
            "where polrelid = 'public.affiliate_clicks'::regclass"
        )
    ).scalars()
    assert set(policies) == {
        "affiliate_clicks_select_own",
        "affiliate_clicks_insert_own",
    }
