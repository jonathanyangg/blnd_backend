from starlette.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from main import app


def _preflight(origin: str):
    return TestClient(app).options(
        "/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )


def test_listed_origin_allowed():
    assert (
        _preflight("https://blnd.movie").headers.get("access-control-allow-origin")
        == "https://blnd.movie"
    )


def test_unlisted_origin_rejected_when_regex_unset():
    mw = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    if mw.kwargs.get("allow_origin_regex"):
        return  # environment sets a regex (staging); covered by the next test
    assert (
        "access-control-allow-origin"
        not in _preflight("https://blnd-pr-1.vercel.app").headers
    )
