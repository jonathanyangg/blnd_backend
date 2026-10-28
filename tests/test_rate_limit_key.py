"""A forged JWT sub must not spend another user's rate-limit bucket."""

from limits import parse
from starlette.requests import Request

from app.core.rate_limit import get_rate_limit_key, limiter

VICTIM = "11111111-1111-1111-1111-111111111111"


def _request(authorization: str | None, host: str = "203.0.113.8") -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": (host, 1234),
        "server": ("test", 80),
    }
    return Request(scope)


def test_forged_sub_does_not_consume_victim_bucket(monkeypatch) -> None:
    """Signature check rejects the forged token, so the hit lands on the IP."""

    def _decode(token: str) -> str:
        if token != "real-token":
            raise ValueError("bad signature")
        return VICTIM

    monkeypatch.setattr("app.dependencies._decode_jwt", _decode)
    forged = (
        "Bearer eyJhbGciOiJub25lIn0."
        "eyJzdWIiOiIxMTExMTExMS0xMTExLTExMTEtMTExMS0xMTExMTExMTExMTEifQ."
    )
    forged_key = get_rate_limit_key(_request(forged))
    real_key = get_rate_limit_key(_request("Bearer real-token"))

    assert forged_key == "ip:203.0.113.8"
    assert VICTIM not in forged_key
    assert real_key == f"user:{VICTIM}"

    item = parse("1/minute")
    assert limiter.limiter.hit(item, forged_key) is True
    assert limiter.limiter.hit(item, forged_key) is False
    assert limiter.limiter.test(item, real_key) is True


def test_missing_token_uses_ip() -> None:
    assert get_rate_limit_key(_request(None, host="198.51.100.4")) == "ip:198.51.100.4"
