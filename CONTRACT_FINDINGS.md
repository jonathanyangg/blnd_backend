# Contract Test Findings

The initial Schemathesis run exposed genuine 5xx responses for valid schema input. These were fixed:

- Malformed UUID and out-of-range numeric values could reach database casts and return 500. They now return `422 VALIDATION_ERROR`.
- Explicitly setting `username` to `null` on `PATCH /auth/profile` could trigger a database NOT NULL error. It now returns `400`.
- `POST /recommendations/{tmdb_id}/hide` inserted a foreign-key row without checking that the movie exists. Unknown movies now return `404`.
- `GET /movies/{tmdb_id}/streaming` cached availability for movies absent from the local movie cache, causing a foreign-key error. Unknown movies now skip the cache write.
- `POST /friends/contacts` stored blank and duplicate phone numbers, causing primary-key conflicts. It now normalizes and deduplicates contacts.

The checked-in `openapi.json` is stale relative to the runtime schema. The contract suite intentionally uses `/openapi.json` from the ASGI app, as requested.
