# Sync Tokens (ETag / If-None-Match)

**Status:** draft — not implemented
**Owner:** jonathan
**Premium:** no

---

## Goal

Stop re-downloading list data that hasn't changed. Today the iOS client caches friends / groups / watched / watchlist in `UserActionCache` and invalidates them by hand at mutation sites. When an invalidation is missed — or when state changed server-side (push, admin action, future multi-device) — the client re-fetches the full payload anyway.

With ETags, the client sends a fingerprint of what it already has; the server replies **HTTP 304 Not Modified** (~200 bytes, no body) when nothing changed, or the full payload + a new fingerprint when it did. Real consistency, near-zero cost for the common case.

---

## What an ETag is (plainly)

An ETag is a short opaque string (e.g. `"a1f3e9"`) the server returns alongside a response body. It's a version stamp. The client caches the body **and** the ETag. On the next request for the same resource, the client sends `If-None-Match: "a1f3e9"`. The server compares:

- Unchanged → `304 Not Modified`, empty body. Client reuses its cache.
- Changed → `200 OK`, full body + new ETag.

The ETag value is arbitrary — it just has to change when the data changes. Two cheap strategies:

1. **Hash-based** — `sha256(json.dumps(payload, sort_keys=True))`. Zero bookkeeping; works for any endpoint. Cost: we still build the full payload server-side, then throw it away on a 304. Fine when the payload is small (friends, groups).
2. **Version-based** — maintain a `<user_id, resource>` → version counter in Redis / a small table. Bump on every mutation. Cost: extra write on mutation, but 304 path can skip payload construction entirely. Worth it only if the payload is expensive to build.

For blnd's endpoints (all small lists), **start with hash-based**. Upgrade specific hot endpoints to version-based only if profiling shows the payload construction is measurable.

---

## Why this beats pure TTL

Current plan (coarse TTL + scenePhase reconcile): after 10 min, throw cache away, re-download everything. Works, but wasteful when nothing changed.

ETag: after 10 min (or at any time — TTL becomes optional), ask "still the same?" — 304 if yes, full payload only when something genuinely changed.

| | TTL only | TTL + ETag |
|---|---|---|
| Staleness ceiling | up to TTL | up to TTL |
| Bytes on "nothing changed" refresh | full payload | ~200 bytes (304) |
| Consistency when user foregrounds | probabilistic | real |
| Server CPU on unchanged refresh | same as full fetch | same (hash-based) / ~zero (version-based) |

---

## Scope

### Endpoints that get ETag support (Phase 1)

All list endpoints on `UserActionCache`'s hot path:

- `GET /friends` — list friends
- `GET /friends/pending` — pending requests
- `GET /groups` — groups list
- `GET /tracking/history` — watched history (capped at 500 on iOS bootstrap)
- `GET /watchlist` — personal watchlist
- `GET /notifications/inbox` — inbox (per-page ETag is tricky; skip initially)

### Endpoints that do NOT need it

- Feed / recommendations — already exclusion-based, always changes on intent.
- Movie detail — cache-controlled by TMDB upstream; URLCache handles this.
- Anything that's already `POST` — ETags are HTTP GET semantics.

---

## Server-side design

### FastAPI approach

Add a reusable dependency / middleware helper that:

1. Runs the endpoint normally to produce `response_data`.
2. Computes `etag = sha256(stable_serialize(response_data))[:16]`.
3. If `request.headers.get("if-none-match")` matches → return `Response(status_code=304)`.
4. Else → normal JSON response with `ETag: "<etag>"` header.

```python
# app/core/etag.py (new)

import hashlib
import json
from fastapi import Request, Response
from fastapi.responses import JSONResponse

def _stable_etag(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]

def etag_response(request: Request, payload) -> Response:
    etag = f'"{_stable_etag(payload)}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return JSONResponse(
        content=payload,
        headers={"ETag": etag, "Cache-Control": "private, must-revalidate"}
    )
```

### Endpoint integration

Each touched endpoint becomes:

```python
@router.get("/friends", response_model=None)  # drop response_model since we manually return
async def list_friends(request: Request, user_id: str = Depends(...), db: Session = Depends(...)):
    payload = services.list_friends(user_id, db)  # dict, not pydantic
    return etag_response(request, payload)
```

Pydantic caveat: `JSONResponse(content=...)` wants a serializable dict, so services should return `.model_dump()` output, not the pydantic model itself. Small refactor, mechanical.

### Stability of the hash

The hash must be **deterministic** given the same logical data. Watch for:

- List ordering — always sort by a stable key (e.g. friend id) before serializing.
- Datetime formatting — use ISO strings, not repr.
- Floats in ratings — already serialized consistently by `json.dumps`.

Wrap the serialization in a tiny helper per resource to make stability explicit.

---

## Client-side design (iOS)

### APIClient changes

Extend `APIClient.request(...)` to accept an optional cached-ETag param and to surface the response ETag + 304 status back to the caller.

```swift
// Networking/APIClient.swift

struct CachedResponse<T: Decodable> {
    let data: T?              // nil if 304
    let etag: String?         // server's new ETag (may equal sent)
    let notModified: Bool     // true if 304
}

func requestWithEtag<T: Decodable>(
    endpoint: String,
    ifNoneMatch: String? = nil
) async throws -> CachedResponse<T> { ... }
```

### UserActionCache integration

Add `etag: String?` alongside cached data:

```swift
@MainActor @Observable
final class UserActionCache {
    private(set) var friends: [FriendResponse] = []
    private(set) var friendsEtag: String?

    func fetchFriends(forceRefresh: Bool = false) async {
        if didLoadFriends, !forceRefresh {
            // Revalidate with ETag — cheap 304 if unchanged
            let result: CachedResponse<FriendListResponse> = try? await APIClient.shared
                .requestWithEtag(endpoint: "/friends", ifNoneMatch: friendsEtag) ?? ...
            if result.notModified { return }           // still fresh
            if let data = result.data {
                friends = data.friends
                friendsEtag = result.etag
            }
            return
        }
        // First load
        ...
    }
}
```

**Key behavior change**: `didLoadFriends` stops being a one-shot flag. Every call now revalidates — but revalidation is cheap (304 on the common path). This deletes most of the "don't forget to invalidate" footgun even before the centralized-invalidation refactor lands.

### scenePhase hook

When app foregrounds after > 5 min in background, call `revalidateAll()` which runs every cached region's ETag check. Cheap set of 304s in the happy case; automatic refresh when anything changed.

---

## API shape

Request (client → server):

```
GET /friends HTTP/1.1
If-None-Match: "a1f3e9b2"
Authorization: Bearer <jwt>
```

Response — unchanged:

```
HTTP/1.1 304 Not Modified
ETag: "a1f3e9b2"
```

Response — changed:

```
HTTP/1.1 200 OK
ETag: "7c4d1e08"
Content-Type: application/json

{ "friends": [...] }
```

Failure modes:

- Client sends stale ETag → server returns 200 + new ETag. Safe.
- Client sends no `If-None-Match` → server returns 200 + ETag. Bootstrap path.
- Response body changed but hash collides (probabilistically impossible for sha256-16) → client keeps old data one cycle longer. Acceptable.

---

## Rollout

### Phase 1 — backend + one endpoint (half day)

1. Add `app/core/etag.py` with `etag_response(request, payload)`.
2. Wire `GET /friends` through it.
3. Verify 304 path with curl + `If-None-Match`.
4. Ship silently — iOS still ignores ETags, endpoint behavior unchanged.

### Phase 2 — remaining endpoints (half day)

5. Wire `/friends/pending`, `/groups`, `/tracking/history`, `/watchlist`.
6. Unit test: mutating data → ETag changes; reading data → ETag stable.

### Phase 3 — iOS consumption (1 day)

7. Extend `APIClient` with `requestWithEtag`.
8. Add `etag` storage to `UserActionCache` regions.
9. Convert `fetchGroups` / `fetchFriends` to revalidate-with-ETag.
10. Add scenePhase reconcile hook in `ContentView` / `MainTabView`.

### Phase 4 — optional polish

11. Promote hot endpoint (probably `/friends`) to version-based ETag if profiling shows payload construction is >50ms p99.
12. Collapse redundant `invalidateFriends()` call sites since they become no-ops (the next fetch will 304 anyway if unchanged).

---

## Non-goals

- **ETags on feed / recommendations** — payload always changes based on `exclude` list; no stable identity to hash against.
- **Weak ETags** (`W/"..."`) — full ETags are simpler; we don't need byte-for-byte equality semantics.
- **Cache-Control: max-age** — we want `must-revalidate` so client always asks. Max-age risks serving stale data without a recheck.
- **Replacing UserActionCache** — this feature layers *on top* of it. The cache stays; ETag just makes revalidation cheap.

---

## Open questions

1. **Should we pair this with centralized invalidation or ship first?** Centralized invalidation is independently valuable (eliminates scattered `invalidate*()` calls); ETags make the residual bugs cheap even if a call is missed. I'd ship ETags first — it reduces the urgency of the refactor.
2. **Per-user or resource-level ETags?** Hash-based is inherently per-user since the payload is per-user. Fine.
3. **How do we expire disk-cached ETag values on iOS logout?** Reset happens in `UserActionCache.reset()` — add `friendsEtag = nil` etc. there.

---

*Last updated: 2026-04-21*
