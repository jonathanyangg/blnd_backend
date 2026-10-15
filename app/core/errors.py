"""Safe error responses and request ids.

Every error body is ``{"error": {"code", "message", "request_id"}, "detail"}``.
``detail`` repeats ``message`` for the iOS 1.1 app, except ``FREE_GROUP_CAP``
and ``GROUP_FULL``, where ``detail`` is ``{"message": <message>}``. Status
codes are left as the raiser set them. Messages never include stack traces,
SQL, upstream bodies, or environment values; those are logged with the
request id instead.
"""

import logging
import re
import uuid
from collections.abc import Mapping

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError
from slowapi.errors import RateLimitExceeded
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from supabase_auth.errors import AuthError, AuthRetryableError

from app.config import settings

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_LEAK_RE = re.compile(
    r"traceback \(most recent call last\)"
    r'|file "[^"]+\.py"'
    r"|\bselect\s+[^\n;]{0,200}\sfrom\s"
    r"|\binsert\s+into\s"
    r"|\bdelete\s+from\s"
    r"|\bupdate\s+\w+\s+set\s"
    r"|sqlalchemy|psycopg|asyncpg"
    r"|postgres(?:ql)?://"
    r"|duplicate key|violates\s+\w+\s+constraint"
    r"|syntax error at or near"
    r"|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
    re.IGNORECASE,
)
_MIN_SECRET_LEN = 8

# Stable codes keyed by the status we already return.
_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    402: "PAYMENT_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}

_DEFAULT_MESSAGES: dict[int, str] = {
    400: "Bad request",
    401: "Invalid or expired token",
    402: "Payment required",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    413: "Payload too large",
    415: "Unsupported media type",
    422: "Invalid request",
    429: "Too many requests",
    500: "Internal server error",
    502: "Upstream request failed",
    503: "Service unavailable, try again",
}

_AUTH_OUTAGE = "Auth service unavailable, try again"
_UPSTREAM_OUTAGE = "Upstream service unavailable, try again"
_UPSTREAM_FAILED = "Upstream request failed"


def code_for_status(status_code: int) -> str:
    """Return the stable code for an HTTP status, or ``HTTP_<status>``."""
    return _STATUS_CODES.get(status_code, f"HTTP_{status_code}")


def default_message(status_code: int) -> str:
    """Return the generic client message for a status code."""
    if status_code in _DEFAULT_MESSAGES:
        return _DEFAULT_MESSAGES[status_code]
    if status_code >= 500:
        return _DEFAULT_MESSAGES[500]
    return _DEFAULT_MESSAGES[400]


def normalize_request_id(raw: str | None) -> str:
    """Accept a caller-supplied id, or generate a UUID when it is unusable.

    Unusable means missing, too long, or containing characters that could
    break a header or a log line. The returned value is safe to echo.
    """
    if raw and _REQUEST_ID_RE.fullmatch(raw):
        return raw
    return str(uuid.uuid4())


def request_id_of(request: Request) -> str:
    """Return the id stored by middleware, or a fresh UUID if it is missing."""
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    return str(uuid.uuid4())


def is_unsafe(message: str) -> bool:
    """True when a string looks like a trace, SQL, an upstream body, or a secret."""
    if "\n" in message or "\r" in message or "\x00" in message:
        return True
    stripped = message.lstrip()
    if stripped.startswith(("{", "[", "<")):
        return True
    if _LEAK_RE.search(message):
        return True
    for value in _secret_values():
        if value in message:
            return True
    return False


def _secret_values() -> list[str]:
    values: list[str] = []
    for name in type(settings).model_fields:
        raw = getattr(settings, name, None)
        if isinstance(raw, str) and len(raw) >= _MIN_SECRET_LEN:
            values.append(raw)
    return values


# Shipped iOS parseDetail only reads detail["message"] when detail is a dict.
# Every other code keeps detail as a string equal to error.message.
_DICT_DETAIL_CODES = frozenset({"FREE_GROUP_CAP", "GROUP_FULL"})


def _json_error(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    detail: str | dict[str, str] | None = None,
) -> JSONResponse:
    """Build the shared error body. ``detail`` matches ``message`` unless overridden."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message, "request_id": request_id},
            "detail": message if detail is None else detail,
        },
        headers={REQUEST_ID_HEADER: request_id},
    )


def _public_http_error(detail: object, status_code: int) -> tuple[str, str]:
    """Return ``(code, message)`` safe to send for an HTTPException.

    A string detail is kept when it is safe, so existing client copy still
    matches. A dict detail may carry ``code`` and ``message`` (group caps);
    only those two fields are published.
    """
    code = code_for_status(status_code)
    message = ""
    if isinstance(detail, str):
        message = detail.strip()
    elif isinstance(detail, dict):
        raw_code = detail.get("code")
        if isinstance(raw_code, str) and _CODE_RE.fullmatch(raw_code):
            code = raw_code.upper()
        raw_message = detail.get("message")
        if isinstance(raw_message, str):
            message = raw_message.strip()
    if not message or is_unsafe(message):
        return code_for_status(status_code), default_message(status_code)
    return code, message


def _header(scope: Scope, name: str) -> str:
    target = name.lower().encode("latin-1")
    for key, value in scope.get("headers", []):
        if key.lower() == target:
            return value.decode("latin-1", errors="replace").strip()
    return ""


class RequestIdMiddleware:
    """Generate or propagate ``X-Request-ID`` and echo it on the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = normalize_request_id(_header(scope, "x-request-id"))
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = request_id
        else:
            state.request_id = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.app(scope, receive, send_with_id)


def _log_http(request_id: str, status_code: int, detail: object) -> None:
    log = logger.error if status_code >= 500 else logger.info
    log(
        "http error request_id=%s status=%s detail=%s",
        request_id,
        status_code,
        detail,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """HTTPException, including 401 bad tokens. Status code is unchanged."""
    request_id = request_id_of(request)
    _log_http(request_id, exc.status_code, exc.detail)
    code, message = _public_http_error(exc.detail, exc.status_code)
    published: str | dict[str, str] = message
    if code in _DICT_DETAIL_CODES:
        published = {"message": message}
    response = _json_error(exc.status_code, code, message, request_id, published)
    extra: Mapping[str, str] | None = exc.headers
    if extra:
        for key, value in extra.items():
            if key.lower() != REQUEST_ID_HEADER.lower():
                response.headers[key] = value
    return response


def _field_error(err: Mapping[str, object]) -> tuple[str, str]:
    """Return ``(field, message)`` with the submitted value removed from the text."""
    loc = err.get("loc") or ()
    if isinstance(loc, (list, tuple)):
        field = ".".join(str(part) for part in loc) or "request"
    else:
        field = "request"
    msg = str(err.get("msg") or "invalid")
    if msg.startswith("Value error, "):
        msg = msg.removeprefix("Value error, ")
    raw = err.get("input")
    if isinstance(raw, str) and len(raw) >= 4 and raw in msg:
        msg = msg.replace(raw, "…")
    return field, msg


def _validation_summary(exc: RequestValidationError) -> str:
    """One line per field. Submitted values are not copied into the line."""
    parts = [f"{field}: {msg}" for field, msg in (_field_error(err) for err in exc.errors())]
    summary = "; ".join(parts) if parts else "Invalid request"
    if len(summary) > 500:
        summary = summary[:497] + "..."
    if is_unsafe(summary):
        return "Invalid request"
    return summary


async def validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 VALIDATION_ERROR. The summary names fields and omits raw input."""
    request_id = request_id_of(request)
    logged = [
        {"loc": err.get("loc"), "type": err.get("type"), "msg": _field_error(err)[1]}
        for err in exc.errors()
    ]
    logger.info("validation error request_id=%s errors=%s", request_id, logged)
    return _json_error(422, "VALIDATION_ERROR", _validation_summary(exc), request_id)


def _upstream_detail(exc: Exception) -> str:
    """Server-side text for an upstream failure. Never returned to the client."""
    if isinstance(exc, httpx.HTTPStatusError):
        body = exc.response.text[:2000]
        return f"status={exc.response.status_code} url={exc.request.url} body={body}"
    if isinstance(exc, APIError):
        return repr(exc)
    return str(exc)


async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    """Supabase auth failures that views did not already convert.

    A 5xx or ``AuthRetryableError`` stays a 503 so the client keeps the
    session and retries. Any other auth rejection stays a 401.
    """
    request_id = request_id_of(request)
    status = getattr(exc, "status", None)
    logger.warning(
        "auth upstream error request_id=%s type=%s status=%s detail=%s",
        request_id,
        type(exc).__name__,
        status,
        exc,
    )
    if isinstance(exc, AuthRetryableError) or (
        isinstance(status, int) and status >= 500
    ):
        return _json_error(503, "SERVICE_UNAVAILABLE", _AUTH_OUTAGE, request_id)
    return _json_error(401, "UNAUTHORIZED", "Invalid or expired token", request_id)


async def http_status_error_handler(
    request: Request, exc: httpx.HTTPStatusError
) -> JSONResponse:
    """TMDB or other HTTP upstream errors that a view did not catch.

    5xx becomes 503. Other statuses are not forwarded: a TMDB 401 must not
    look like an expired user token. The upstream body is only logged.
    """
    request_id = request_id_of(request)
    logger.warning(
        "upstream http error request_id=%s detail=%s",
        request_id,
        _upstream_detail(exc),
    )
    upstream = exc.response.status_code
    if upstream >= 500:
        return _json_error(503, "SERVICE_UNAVAILABLE", _UPSTREAM_OUTAGE, request_id)
    if upstream == 429:
        return _json_error(429, "RATE_LIMITED", "Too many requests", request_id)
    if upstream == 404:
        return _json_error(404, "NOT_FOUND", "Not found", request_id)
    return _json_error(502, "BAD_GATEWAY", _UPSTREAM_FAILED, request_id)


async def http_request_error_handler(
    request: Request, exc: httpx.RequestError
) -> JSONResponse:
    """Network failures reaching an upstream host. Always a retryable 503."""
    request_id = request_id_of(request)
    logger.warning(
        "upstream network error request_id=%s detail=%s",
        request_id,
        _upstream_detail(exc),
    )
    return _json_error(503, "SERVICE_UNAVAILABLE", _UPSTREAM_OUTAGE, request_id)


async def supabase_api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """PostgREST errors. Connection loss is 503; anything else is 502.

    ``message``, ``details``, and ``hint`` often contain SQL, so none of them
    are copied into the response.
    """
    request_id = request_id_of(request)
    logger.warning(
        "supabase error request_id=%s detail=%s",
        request_id,
        _upstream_detail(exc),
    )
    code = str(exc.code or "")
    message = str(exc.message or "")
    if code == "PGRST000" or "could not connect" in message.lower():
        return _json_error(503, "SERVICE_UNAVAILABLE", _UPSTREAM_OUTAGE, request_id)
    return _json_error(502, "BAD_GATEWAY", _UPSTREAM_FAILED, request_id)


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429 RATE_LIMITED. The limiter's internal detail string is not returned."""
    request_id = request_id_of(request)
    logger.info("rate limit request_id=%s detail=%s", request_id, exc.detail)
    return _json_error(429, "RATE_LIMITED", "Too many requests", request_id)


async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last resort. The client only sees a fixed 500 message.

    The exception text and traceback are logged with the request id. They are
    never placed on the response, even when the text itself looks harmless.
    """
    request_id = request_id_of(request)
    logger.exception("unhandled error request_id=%s detail=%s", request_id, exc)
    return _json_error(
        500, "INTERNAL_ERROR", default_message(500), request_id
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install the global handlers. More specific types win over Exception."""
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(AuthError, auth_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(httpx.HTTPStatusError, http_status_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(httpx.RequestError, http_request_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(APIError, supabase_api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_handler)
