# Error codes

Every error response uses this shape. `detail` is the same string as `error.message` so the shipped iOS 1.1 app, which reads `detail`, keeps working.

```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Invalid or expired token",
    "request_id": "2f0c1c4e-7b1a-4e0a-9c2d-6a1b0e5d4c3a"
  },
  "detail": "Invalid or expired token"
}
```

`code` is a stable `SCREAMING_SNAKE` string. HTTP status codes are unchanged.

`X-Request-ID` is read from the request when it is a token of letters, digits, `.`, `_`, or `-` (max 128 characters). Otherwise the server generates a UUID. The same value is returned in the `X-Request-ID` response header and in `error.request_id`.

The server logs the original exception, including upstream bodies, with that request id. The response never includes a stack trace, SQL, an upstream body, or an environment value.

## Codes

| Code | Status | Meaning | iOS handling |
| --- | --- | --- | --- |
| `BAD_REQUEST` | 400 | The request was rejected for a reason `message` explains (a business rule, or a client error that is not schema validation). | Show `message`. |
| `GROUP_FULL` | 400 | The group is already at its member cap. `message` includes the cap. | Show `message`. |
| `UNAUTHORIZED` | 401 | The access token is missing, invalid, or expired, or a refresh token was rejected. | Call refresh. If that refresh also returns 401, the session is dead: go to login. Do not log the user out on a 401 from any other call until refresh has failed. |
| `PAYMENT_REQUIRED` | 402 | A paid action was rejected and no more specific code was set. | Show `message` and the upgrade path. |
| `FREE_GROUP_CAP` | 402 | A free group is at its member cap. `message` includes the free and blnd+ caps. | Show `message` and the blnd+ upgrade path. |
| `FORBIDDEN` | 403 | The caller is signed in but is not allowed to do this. | Show `message`. Do not refresh. |
| `NOT_FOUND` | 404 | The resource does not exist or is hidden. | Show `message`, or an empty state. |
| `METHOD_NOT_ALLOWED` | 405 | This HTTP method is not valid for the path. | Treat as a client bug. |
| `CONFLICT` | 409 | The request conflicts with current state. | Show `message`. |
| `PAYLOAD_TOO_LARGE` | 413 | The upload is over the size limit. | Show `message`. |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | The body media type is not supported. | Treat as a client bug. |
| `VALIDATION_ERROR` | 422 | Body or query failed schema validation. `message` is a per-field summary (`body.password: Password must be at least 8 characters`) and does not echo submitted values. | Show the summary on the form. |
| `RATE_LIMITED` | 429 | Too many requests, or an upstream rate limit. | Wait and retry. Do not log the user out. |
| `INTERNAL_ERROR` | 500 | Unexpected server error. The client message is always `Internal server error`. | Generic error. Retry later. Include `request_id` in a bug report. |
| `BAD_GATEWAY` | 502 | Supabase or another upstream returned an error that is not an outage. | Generic error. Retry later. |
| `SERVICE_UNAVAILABLE` | 503 | Auth, Supabase, or TMDB is down or unreachable, or returned a 5xx. | Keep the session and retry. Do not log the user out. |

`HTTP_<status>` is used only if a handler raises a status that is not in this table. iOS should show `message` and not special-case it.

## Auth refresh

| Call | Status | Code | What iOS does |
| --- | --- | --- | --- |
| Any API call with a bad or expired access token | 401 | `UNAUTHORIZED` | Refresh the session. |
| `POST /auth/refresh` with a bad or expired refresh token | 401 | `UNAUTHORIZED` | Go to login. |
| `POST /auth/refresh` while Supabase is down, timing out, or returning 5xx | 503 | `SERVICE_UNAVAILABLE` | Keep the stored session and retry. |
