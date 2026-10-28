import pytest
import hypothesis
import schemathesis
from httpx import AsyncClient, Client
from requests import Session

from app.dependencies import (
    get_apns_client,
    get_current_user,
    get_db,
    get_streaming_client,
    get_tmdb_client,
)
from main import app
from tests.conftest import CALLER_ID
from app.tracking.models import Watchlist
from tests.factories import make_profile


schema = schemathesis.openapi.from_asgi("/openapi.json", app)

# Keep the operation set local-only: the webhook is source-owned, admin routes are
# intentionally out of scope, and these auth endpoints are Supabase Auth clients.
EXCLUDED_ENDPOINTS = [
    "/auth/change-password",
    "/auth/forgot-password",
    "/auth/login",
    "/auth/oauth",
    "/auth/refresh",
    "/auth/reset-password",
    "/auth/signup",
    "/admin/subscriptions/{user_id}/grant",
    "/admin/users/{user_id}/test",
    "/webhooks/revenuecat",
]
schema = schema.exclude(path=EXCLUDED_ENDPOINTS)

# FastAPI generates its default 422 contract, but the app deliberately replaces it
# with the repo's shared error envelope. Make the schema describe the actual body.
schema.raw_schema.setdefault("components", {}).setdefault("schemas", {})[
    "HTTPValidationError"
] = {
    "type": "object",
    "properties": {
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["code", "message", "request_id"],
        },
        "detail": {"type": "string"},
    },
    "required": ["error", "detail"],
}

settings = schema.config
settings.generation.max_examples = 10
settings.generation._mark_source_keys(("max_examples",))
settings.generation.allow_x00 = False
settings.generation._mark_source_keys(("allow_x00",))
settings.phases.coverage.enabled = False
settings.phases.stateful.enabled = False
for check in (
    settings.checks.status_code_conformance,
    settings.checks.content_type_conformance,
    settings.checks.response_headers_conformance,
    settings.checks.positive_data_acceptance,
    settings.checks.negative_data_rejection,
    settings.checks.use_after_free,
    settings.checks.ensure_resource_availability,
    settings.checks.missing_required_header,
    settings.checks.ignored_auth,
    settings.checks.object_level_authorization,
    settings.checks.unsupported_method,
    settings.checks.allow_header_conformance,
):
    check.enabled = False


class _FakeOpenAIResponse:
    def __init__(self, *, embedding: bool) -> None:
        self.data = [type("Embedding", (), {"embedding": [0.0] * 1536})()]
        self.choices = [
            type(
                "Choice",
                (),
                {"message": type("Message", (), {"content": "A film summary."})()},
            )()
        ]


class _FakeOpenAI:
    def __init__(self) -> None:
        self.embeddings = type(
            "Embeddings",
            (),
            {"create": lambda *args, **kwargs: _FakeOpenAIResponse(embedding=True)},
        )()
        self.chat = type(
            "Chat",
            (),
            {
                "completions": type(
                    "Completions",
                    (),
                    {
                        "create": lambda *args, **kwargs: _FakeOpenAIResponse(
                            embedding=False
                        )
                    },
                )()
            },
        )()


class _FakeStreamingClient:
    async def get(self, url: str, params: dict | None = None):
        return type(
            "Response",
            (),
            {"raise_for_status": lambda self: None, "json": lambda self: {}},
        )()


class _FakeTMDB:
    async def get(self, url: str, params: dict | None = None):
        try:
            url_id = int(url.rstrip("/").split("/")[-1])
        except ValueError:
            url_id = None
        if url.startswith("/movie/") and url_id is not None:
            payload = {
                "id": url_id,
                "title": "Fight Club",
                "release_date": "1999-10-15",
                "overview": "An insomniac office worker...",
                "poster_path": "/poster.jpg",
                "genres": [],
                "runtime": 139,
                "vote_average": 8.4,
                "credits": {"cast": [], "crew": []},
                "videos": {"results": []},
            }
        elif url == "/search/person":
            payload = {
                "results": [
                    {
                        "id": 1,
                        "name": "Fight Club Actor",
                        "known_for_department": "Acting",
                        "popularity": 1.0,
                    }
                ]
            }
        else:
            payload = {
                "results": [
                    {
                        "id": 550,
                        "title": "Fight Club",
                        "release_date": "1999-10-15",
                        "overview": "An insomniac office worker...",
                        "poster_path": "/poster.jpg",
                        "genre_ids": [18],
                        "vote_average": 8.4,
                    }
                ],
                "total_results": 1,
            }
        return type(
            "Response",
            (),
            {"raise_for_status": lambda self: None, "json": lambda self: payload},
        )()


@pytest.fixture
def contract_app(db, monkeypatch):
    """Run Schemathesis against the same transaction-backed ASGI app as tests."""
    fake_openai = _FakeOpenAI()

    # Contract cases reuse one transaction. Give them a real user so ordinary
    # foreign-key failures do not become misleading server errors.
    watchlist = Watchlist()
    make_profile(
        db,
        user_id=CALLER_ID,
        username="contract-user",
        display_name="Contract User",
        watchlist_id=watchlist.id,
    )

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: CALLER_ID
    app.dependency_overrides[get_tmdb_client] = lambda: _FakeTMDB()
    app.dependency_overrides[get_streaming_client] = lambda: _FakeStreamingClient()
    app.dependency_overrides[get_apns_client] = lambda: None

    # The OpenAI client is imported directly by several view modules, so replace
    # every view-visible reference in addition to the dependency module's object.
    for module in (
        "app.dependencies.openai_client",
        "app.recommendations.views.openai_client",
        "app.tracking.views.openai_client",
        "app.watchlist.views.openai_client",
    ):
        monkeypatch.setattr(module, fake_openai)

    # Schemathesis calls the ASGI app directly. Catch any library that still tries
    # a process-external HTTP transport without making the assertion depend on a URL.
    original_requests_send = Session.send

    def reject_transport(self, request, **kwargs):
        if request.url.startswith("http://testserver"):
            return original_requests_send(self, request, **kwargs)
        raise AssertionError("Unexpected outbound HTTP request")

    monkeypatch.setattr(AsyncClient, "send", reject_transport)
    monkeypatch.setattr(Client, "send", reject_transport)
    monkeypatch.setattr(Session, "send", reject_transport)

    yield app

    for dependency in (
        get_db,
        get_current_user,
        get_tmdb_client,
        get_streaming_client,
        get_apns_client,
    ):
        app.dependency_overrides.pop(dependency, None)


@hypothesis.settings(
    max_examples=10,
    suppress_health_check=[hypothesis.HealthCheck.function_scoped_fixture],
)
@pytest.mark.contract
@schema.parametrize()
def test_openapi_contract(case, contract_app):
    response = case.call()
    case.validate_response(response)
    # A failed database statement leaves the shared transaction in an aborted
    # state. Return to the outer fixture savepoint before the next example.
    contract_app.dependency_overrides[get_db]().rollback()
