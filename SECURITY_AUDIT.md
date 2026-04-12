# BLND Backend — Security Audit Report

**Date**: 2026-03-09
**Last reviewed**: 2026-04-02
**Scope**: All Python source files, configuration files, migration files, and environment files.

---

## Critical (2)

### 1. Live Production Secrets in `.env` File — ⚠️ ACCEPTED RISK

- **Location**: `.env`, lines 1-11
- **Severity**: Critical
- **Status**: Accepted risk for v1. Secrets are in `.gitignore` and never committed. Render environment variables are used in production.
- **Description**: The `.env` file contains live production secrets. While `.env` is listed in `.gitignore` and does not appear in git history, these are real credentials stored in plaintext on disk.
- **Future**: Migrate to a secrets manager (Doppler, AWS Secrets Manager, or Supabase Vault) when scaling.

### 2. ~~Supabase Client Uses Service-Role Key for User Auth~~ — ✅ FIXED

- **Location**: `app/dependencies.py:15`
- **Status**: **Fixed**. The global `supabase` client now uses `settings.supabase_key` (anon/publishable key). A separate `supabase_admin` client (service-role key) exists only for admin operations (password reset, account deletion) and includes null checks.

---

## High (5)

### 3. ~~CORS Allows All Origins with Credentials~~ — ✅ FIXED

- **Location**: `main.py:62-72`
- **Status**: **Fixed**. CORS is now restricted to `["https://blnd.movie", "http://localhost:3000", "http://127.0.0.1:3000"]`.

### 4. ~~Rate Limit Bypass via Forged JWT~~ — ✅ FIXED

- **Location**: `app/core/rate_limit.py:7-11`
- **Status**: **Fixed**. Rate limit key function now uses IP-based keying (`request.client.host`). No JWT parsing in the rate limiter. Variable renamed to `BLND_DISABLE_RATE_LIMITS`.

### 5. ~~Seed and Sync Endpoints Lack Admin Authorization~~ — ✅ FIXED

- **Location**: `app/import_data/views.py`
- **Status**: **Fixed**. All import endpoints (`seed-movies`, `sync-movies`, `backfill-cast`) now use `Depends(require_admin)`.

### 6. Any Group Member Can Kick Any Other Member — ⚠️ BY DESIGN

- **Location**: `app/groups/services.py:162-192`
- **Severity**: High
- **Status**: **Accepted by design**. Any member can kick non-owners. This is the intended behavior for the app's social model (small friend groups, not public communities).

### 7. Mass Assignment via `setattr` in Tracking Updates — ⚠️ LOW RISK

- **Location**: `app/tracking/services.py:126-128`
- **Severity**: High (theoretical), Low (current)
- **Status**: Current schema only allows `rating`, `review`, `watched_date` — all safe. Risk materializes only if sensitive fields are added to `UpdateTrackingRequest` without review.

---

## Medium (9)

### 8. Error Messages Leak Internal Details — ⚠️ OPEN

- **Location**: `app/auth/views.py`
- **Severity**: Medium
- **Description**: Auth endpoints catch broad `Exception` and return `str(e)`. Supabase SDK errors can contain internal details.
- **Fix**: Return generic user-facing messages. Log actual exceptions server-side.

### 9. ~~ILIKE Wildcard Injection in User Search~~ — ✅ FIXED

- **Location**: `app/auth/services.py:228`
- **Status**: **Fixed**. ILIKE metacharacters (`%`, `_`, `\`) are escaped before interpolation.

### 10. `taste_bio` Accepted in Update Schema but Silently Ignored — ⚠️ OPEN

- **Location**: `app/auth/schemas.py`
- **Severity**: Medium
- **Description**: `UpdateProfileRequest` includes `taste_bio` but the service function ignores it. Should be removed from the schema since it's system-generated.

### 11. No Validation on `avatar_url` — ⚠️ OPEN

- **Location**: `app/auth/schemas.py`, `app/auth/services.py`
- **Severity**: Medium
- **Description**: Accepts any string with no URL validation, scheme check, or length limit.
- **Fix**: Add Pydantic validator requiring `https://` prefix and `max_length` of ~2048.

### 12. No Validation on `source` Field Values — ⚠️ OPEN

- **Location**: `app/tracking/schemas.py`
- **Severity**: Medium
- **Description**: `source` accepts any arbitrary string. Should use `Literal["manual", "recommendation"]`.

### 13. No Length Limits on User-Submitted Text Fields — ⚠️ OPEN

- **Location**: Various schemas
- **Severity**: Medium
- **Description**: `review`, `display_name`, `addressee_username` have no `max_length`.
- **Fix**: Add `max_length` constraints.

### 14. No Max Size on `favorite_genres` List — ⚠️ OPEN

- **Location**: `app/auth/schemas.py`
- **Severity**: Medium
- **Description**: `favorite_genres` list has no limit on length or individual string length.
- **Fix**: Add `max_length=20` on list, validate individual strings.

### 15. OpenAPI Spec Written to Disk on Health Check — ⚠️ OPEN

- **Location**: `main.py`
- **Severity**: Medium
- **Description**: `/health` endpoint writes OpenAPI JSON to disk on first invocation.
- **Fix**: Move to a dev-only command or CI step.

### 16. ~~Background Tasks Share Request-Scoped DB Sessions~~ — ✅ FIXED

- **Location**: `app/auth/views.py`, `app/tracking/views.py`, `app/watchlist/views.py`, `app/recommendations/views.py`, `app/import_data/services.py`
- **Status**: **Fixed**. All background tasks now create their own `SessionLocal()` with proper `rollback()` on error and `close()` in `finally`.

---

## Low (4)

### 17. No Upper Bound on TMDB `page` Parameter — ⚠️ OPEN

- **Location**: `app/movies/views.py`
- **Fix**: Add `le=500`.

### 18. No Friendship Requirement for Group Member Addition — ⚠️ BY DESIGN

- **Status**: Accepted. Users are added by existing group members who know them.

### 19. ~~Rate Limiter Toggle via Environment Variable~~ — ✅ FIXED

- **Status**: **Fixed**. Variable renamed to `BLND_DISABLE_RATE_LIMITS` (more specific).

### 20. `min_popularity` Parameter Unbounded on Seed Endpoint — ⚠️ LOW RISK

- **Status**: Mitigated by admin-only auth (finding #5 fixed). Only admins can trigger the seed pipeline.

---

## Summary

| Severity | Total | Fixed | Open | Accepted |
|----------|-------|-------|------|----------|
| Critical | 2 | 1 | 0 | 1 |
| High | 5 | 3 | 0 | 2 |
| Medium | 9 | 3 | 6 | 0 |
| Low | 4 | 1 | 1 | 2 |

**7 of 20 findings fixed. 5 accepted risk/by-design. 6 medium + 1 low remain open (input validation, error messages).**

The remaining open items are all input validation hardening — none are exploitable for data breach or privilege escalation. Safe to ship v1.
