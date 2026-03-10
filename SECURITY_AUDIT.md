# BLND Backend — Security Audit Report

**Date**: 2026-03-09
**Scope**: All Python source files, configuration files, migration files, and environment files.

---

## Critical (2)

### 1. Live Production Secrets in `.env` File

- **Location**: `.env`, lines 1-11
- **Severity**: Critical
- **Description**: The `.env` file contains live production secrets: Supabase service key, database password embedded in the `DATABASE_URL`, OpenAI API key, and TMDB JWT bearer token. While `.env` is listed in `.gitignore` and does not appear in git history, these are real credentials stored in plaintext on disk.
- **Impact**: Any filesystem access (compromised machine, leaked backup, accidental commit) gives an attacker full admin access to the Supabase project (service key bypasses all RLS), direct read/write to the Postgres database, ability to make OpenAI API calls on the owner's billing, and TMDB API access.
- **Fix**: Rotate all secrets immediately as a precaution. Migrate to a secrets manager (Doppler, AWS Secrets Manager, or Supabase Vault). Never store database passwords in connection string literals. Run `git log --all --diff-filter=A -- .env` to confirm it was never committed.

### 2. Supabase Client Uses Service-Role Key for User Auth

- **Location**: `app/dependencies.py:14`
- **Severity**: Critical
- **Description**: `create_client(settings.supabase_url, settings.supabase_service_key)` initializes the global Supabase client with the service-role key. This client is imported throughout the codebase for `supabase.auth.get_user()` calls. The service-role key bypasses all Row Level Security policies. While `get_user()` itself is a safe operation, the same client object could be used for data operations in any future code path, silently bypassing RLS.
- **Impact**: Any code that accidentally uses this `supabase` client for Supabase data operations (insert, select, update, delete via the Supabase SDK) will bypass all RLS policies. The service key is also the most sensitive credential — a leak is far more damaging than a publishable key leak.
- **Fix**: Use the publishable (anon) key for the auth-verification client. `supabase.auth.get_user(token)` works with the anon key. Reserve a separate service-role client only if admin-level operations are genuinely needed, and never expose it as a module-level import.

---

## High (5)

### 3. CORS Allows All Origins with Credentials

- **Location**: `main.py:23-29`
- **Severity**: High
- **Description**: CORS is configured as `allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]`. This permits any website to make cross-origin requests to the API. Although auth tokens are passed via the `Authorization` header (not cookies), the wildcard origin means any malicious site can freely interact with the API if it obtains a token.
- **Impact**: If a user's JWT is stolen via XSS on any domain, there is no CORS layer preventing the attacker's site from making authenticated requests. It also enables CSRF-like attacks in edge cases.
- **Fix**: Replace `allow_origins=["*"]` with explicit allowed origins: `["https://your-app.com", "http://localhost:3000"]`. Remove `allow_credentials=True` if cookies are not used for auth.

### 4. Rate Limit Bypass via Forged JWT

- **Location**: `app/core/rate_limit.py:17`
- **Severity**: High
- **Description**: The rate limit key function extracts the user identity by decoding the JWT with `options={"verify_signature": False}`. This means the signature is never checked. An attacker can craft a JWT with an arbitrary `sub` claim to get a fresh rate limit bucket for every request.
- **Impact**: Complete bypass of all rate limits. An attacker sends each request with a JWT containing a different random `sub` value, getting unlimited requests per time window. This defeats LIMIT_HEAVY (seed pipeline, 1/day), LIMIT_IMPORT (Letterboxd, 3/hour), LIMIT_REFRESH (taste rebuild, 5/hour), LIMIT_SEARCH (30/min), and LIMIT_DEFAULT (60/min).
- **Fix**: Fall back to IP-based rate limiting in the key function. The actual auth check (`get_current_user`) already verifies the JWT via Supabase. The rate limiter should not trust unverified tokens:
  ```python
  def get_rate_limit_key(request: Request) -> str:
      return _get_ip(request)
  ```

### 5. Seed and Sync Endpoints Lack Admin Authorization

- **Location**: `app/import_data/views.py:48-56` (seed-movies) and `69-76` (sync-movies)
- **Severity**: High
- **Description**: `POST /import/seed-movies` and `POST /import/sync-movies` require only a valid JWT — any authenticated user can trigger them. These endpoints launch background pipelines that make thousands of TMDB API calls and hundreds of OpenAI embedding API calls. The `min_popularity` parameter on seed-movies is also user-controlled, allowing a low value (e.g., `0.01`) to maximize the number of movies processed.
- **Impact**: Any registered user can trigger expensive operations that consume TMDB API quota and OpenAI billing. With the rate limit bypass (finding #4), this can be done repeatedly.
- **Fix**: Add admin-only authorization. Check `user_id` against a hardcoded admin UUID list or an `is_admin` column on the Profile model:
  ```python
  ADMIN_IDS = {"uuid-of-admin-user"}
  if _user_id not in ADMIN_IDS:
      raise HTTPException(status_code=403, detail="Admin only")
  ```

### 6. Any Group Member Can Kick Any Other Member

- **Location**: `app/groups/services.py:158-187`
- **Severity**: High
- **Description**: The `kick_member` function only verifies that the caller is a member of the group and that the target is not the owner. Any member can kick any other non-owner member. The docstring confirms this design: "Anyone can kick anyone except the owner."
- **Impact**: A newly added group member can immediately kick all other members (except the owner), destroying the group. This enables griefing — a malicious user added to a group of 10 people could remove the other 8 members instantly.
- **Fix**: Restrict kick privileges to the group owner:
  ```python
  if str(group.created_by) != user_id:
      raise HTTPException(403, "Only the group owner can kick members")
  ```

### 7. Mass Assignment via `setattr` in Tracking Updates

- **Location**: `app/tracking/services.py:126-128`
- **Severity**: High
- **Description**: `update_watched_movie` iterates over `updates.model_dump(exclude_unset=True)` and applies each field via `setattr(entry, field, value)`. The `UpdateTrackingRequest` schema currently has `rating`, `review`, and `watched_date`, which are safe. However, this pattern blindly maps request fields to model attributes. If the schema is ever expanded to include additional fields (e.g., `liked`, `source`), those would be directly settable by the user without review.
- **Impact**: Currently limited, but introduces a persistent vulnerability surface. If `source`, `user_id`, `id`, or other sensitive fields are ever added to `UpdateTrackingRequest`, they would be silently writable by any user.
- **Fix**: Replace the dynamic `setattr` loop with explicit field assignments:
  ```python
  data = updates.model_dump(exclude_unset=True)
  if "rating" in data: entry.rating = data["rating"]
  if "review" in data: entry.review = data["review"]
  if "watched_date" in data: entry.watched_date = data["watched_date"]
  ```

---

## Medium (9)

### 8. Error Messages Leak Internal Details

- **Location**: `app/auth/views.py:33-34, 42-43, 51-52, 90-91`
- **Severity**: Medium
- **Description**: The signup, login, refresh, and profile update endpoints catch broad `Exception` and return `str(e)` as the HTTP response detail. Supabase SDK errors can contain internal details about the auth infrastructure, connection state, or configuration.
- **Impact**: Internal error strings from the Supabase SDK could leak infrastructure details (database hostnames, configuration errors, stack traces in some SDK versions) to the client.
- **Fix**: Return generic user-facing messages: `"Signup failed"`, `"Invalid credentials"`, `"Session refresh failed"`, `"Update failed"`. Log the actual exception detail server-side with `logger.exception(...)`.

### 9. ILIKE Wildcard Injection in User Search

- **Location**: `app/auth/services.py:79`
- **Severity**: Medium
- **Description**: The user search query is inserted into an ILIKE pattern as `f"{query}%"`. While SQLAlchemy parameterizes the value (preventing SQL injection), the `query` string can contain ILIKE metacharacters (`%` and `_`). Sending `q=%` matches every username. Sending `q=_` matches all single-character usernames. This bypasses the prefix-search intent.
- **Impact**: An attacker can enumerate the entire user directory by sending `q=%`, retrieving up to 10 results per request. Combined with pagination or iterative queries (`q=a%`, `q=b%`...), the full username list can be extracted.
- **Fix**: Escape ILIKE wildcards before interpolation:
  ```python
  escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
  .filter(Profile.username.ilike(f"{escaped}%"))
  ```

### 10. `taste_bio` Accepted in Update Schema but Silently Ignored

- **Location**: `app/auth/schemas.py:78`, `app/auth/services.py:94-128`
- **Severity**: Medium
- **Description**: `UpdateProfileRequest` includes `taste_bio: str | None = None`, but the `update_profile` service function has no handler for it — it only processes `username`, `display_name`, `avatar_url`, and `favorite_genres`. The `taste_bio` field is supposed to be system-generated by the LLM. Accepting it in the schema creates a misleading API contract.
- **Impact**: If a `taste_bio` handler is added later, users could inject arbitrary text, bypassing the LLM generation pipeline. Currently, the field is silently ignored, which is confusing for API consumers.
- **Fix**: Remove `taste_bio` from `UpdateProfileRequest` since it should only be set by the recommendation system.

### 11. No Validation on `avatar_url`

- **Location**: `app/auth/schemas.py:77`, `app/auth/services.py:118`
- **Severity**: Medium
- **Description**: The `avatar_url` field accepts any string with no URL validation, no scheme check, and no length limit. A user could set it to `javascript:alert(1)`, a `data:` URI containing a large payload, or an arbitrarily long string.
- **Impact**: Stored XSS if the frontend renders the URL in an `href` or `src` without sanitization. Storage abuse with extremely long strings. Potential phishing via malicious redirect URLs.
- **Fix**: Add a Pydantic validator requiring `https://` prefix and a `max_length` of ~2048. Optionally restrict to the Supabase Storage domain pattern.

### 12. No Validation on `source` Field Values

- **Location**: `app/tracking/schemas.py:11, 39`
- **Severity**: Medium
- **Description**: `source: str = "manual"` on `TrackMovieRequest` and `AddToWatchlistRequest` accepts any arbitrary string. The intended values are `"manual"`, `"recommendation"`, and `"letterboxd_import"` (set server-side).
- **Impact**: Users can pollute source tracking data with arbitrary values, undermining the analytics feedback loop designed to measure recommendation quality.
- **Fix**: Use `Literal["manual", "recommendation"]` for user-facing schemas. The `"letterboxd_import"` value is set server-side and does not need to be in the user-facing enum.

### 13. No Length Limits on User-Submitted Text Fields

- **Location**: `app/tracking/schemas.py:9, 16` (`review`), `app/auth/schemas.py:29, 76` (`display_name`), `app/friends/schemas.py:7` (`addressee_username`)
- **Severity**: Medium
- **Description**: Multiple user-submitted text fields have no `max_length` constraint: `review` can be any length, `display_name` can be any length, `addressee_username` in friend requests has no length limit.
- **Impact**: Storage abuse, potential DoS via large payloads, and degraded performance when these fields are returned in list responses viewed by other users.
- **Fix**: Add `max_length` constraints: `review` (~10,000), `display_name` (~100), `addressee_username` (~30 to match username limits).

### 14. No Max Size on `favorite_genres` List

- **Location**: `app/auth/schemas.py:79`
- **Severity**: Medium
- **Description**: `favorite_genres: list[str] | None` has no limit on list length or individual string length. A user could send a list with thousands of entries or entries with very long strings.
- **Impact**: Storage abuse in the JSONB column. Performance degradation in recommendation computation, which iterates over genre lists for overlap calculations (Jaccard similarity in `ranking.py`).
- **Fix**: Add constraints: `Field(default=None, max_length=20)` on the list, and validate individual string lengths (e.g., max 50 chars each).

### 15. OpenAPI Spec Written to Disk on Health Check

- **Location**: `main.py:49-56`
- **Severity**: Medium
- **Description**: The `/health` endpoint writes the full OpenAPI JSON spec to `openapi.json` in the project root on first invocation. This is a side effect on an unauthenticated endpoint. The spec contains all endpoint paths, request/response schemas, and parameter details.
- **Impact**: If the production web server or container serves static files from the project root, the complete API specification becomes publicly accessible. Even without static serving, this is unnecessary disk I/O in production and creates a predictable file at a known path.
- **Fix**: Remove this from the health endpoint. Generate the OpenAPI spec as a dev-only command or CI step instead.

### 16. Background Tasks Share Request-Scoped DB Sessions

- **Location**: `app/auth/views.py:98`, `app/tracking/views.py:14-18`
- **Severity**: Medium
- **Description**: Both `_trigger_taste_rebuild` (tracking) and the genre-change handler (auth) pass the request-scoped `db` session to `background_tasks.add_task()`. The `get_db()` generator closes the session when the request finishes (in its `finally` block), but the background task may still be executing `rebuild_taste_profile` with that closed session.
- **Impact**: Race condition causing SQLAlchemy errors (`Session is closed`), silent failures in taste profile rebuilds, or potential data corruption if the session is reused.
- **Fix**: Create a fresh `SessionLocal()` inside the background task, following the same pattern used in `_run_seed_pipeline_async` in `import_data/views.py`. The background task function should manage its own session lifecycle.

---

## Low (4)

### 17. No Upper Bound on TMDB `page` Parameter

- **Location**: `app/movies/views.py:22, 44, 67, 92`
- **Severity**: Low
- **Description**: `page: int = Query(default=1, ge=1)` has no upper bound. TMDB's API caps results at page 500, but the backend does not enforce this.
- **Impact**: Requesting very high page numbers results in wasted TMDB API calls that return errors or empty results, consuming rate limit quota.
- **Fix**: Add `le=500` to match TMDB's maximum.

### 18. No Friendship Requirement for Group Member Addition

- **Location**: `app/groups/services.py:113-155`
- **Severity**: Low
- **Description**: Any group member can add any user by username without requiring a friendship. The target user is not notified and does not consent.
- **Impact**: Users can be added to unwanted groups, exposing their taste data through group recommendations. More of a design/privacy concern than a direct security vulnerability.
- **Fix**: Consider requiring the target to be a friend of at least one group member, or implementing group invitations that require acceptance.

### 19. Rate Limiter Toggle via Environment Variable

- **Location**: `app/core/rate_limit.py:26`
- **Severity**: Low
- **Description**: Setting `TESTING=true` disables all rate limits. If this is accidentally set in a production environment, all protections are removed.
- **Impact**: All rate limits silently disabled in production.
- **Fix**: Use a more specific variable name (e.g., `BLND_DISABLE_RATE_LIMITS`) and log a warning when rate limiting is disabled.

### 20. `min_popularity` Parameter Unbounded on Seed Endpoint

- **Location**: `app/import_data/views.py:52`
- **Severity**: Low
- **Description**: `min_popularity: float = 5.0` has no lower bound. A user could pass `min_popularity=0.001` to seed hundreds of thousands of movies, massively amplifying TMDB and OpenAI API costs.
- **Impact**: Combined with finding #5 (no admin check), any user can trigger a very expensive pipeline.
- **Fix**: Add `Query(default=5.0, ge=1.0)` to enforce a minimum. This is secondary to adding admin-only auth (finding #5).

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| Critical | 2 | Secrets management, service key misuse |
| High | 5 | CORS, rate limit bypass, missing admin auth, privilege escalation, mass assignment |
| Medium | 9 | Information leakage, input validation gaps, shared DB sessions |
| Low | 4 | Missing bounds, design concerns |

## Priority Remediation Order

1. **Switch Supabase client to anon key** for auth verification (Critical #2)
2. **Fix rate limit key function** — use IP-based keying instead of trusting unverified JWTs (High #4)
3. **Restrict CORS origins** to known frontend domains (High #3)
4. **Add admin-only auth** on seed/sync endpoints (High #5)
5. **Restrict kick to group owner only** (High #6)
6. **Replace `setattr` with explicit field assignment** (High #7)
7. **Add input validation** across all schemas — `max_length`, URL validation, enum constraints (Medium #11-14)
8. **Fix background task DB session handling** (Medium #16)
9. **Sanitize error messages** in auth endpoints (Medium #8)
10. **Rotate all secrets** and migrate to a secrets manager (Critical #1)
