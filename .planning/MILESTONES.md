# Milestones

## v1.0 Letterboxd Import (Shipped: 2026-03-10)

**Phases completed:** 3 phases, 6 plans
**Timeline:** 6 days (2026-03-03 → 2026-03-09)
**App code:** ~2,062 LOC Python + 179 LOC SQL

**Delivered:** Users can import their complete Letterboxd history into BLND with a single zip upload — watched movies, ratings, reviews, watchlist, and likes all transfer accurately.

**Key accomplishments:**
- Database schema extended with `liked` column and `watchlist_movies` table via Supabase migrations
- SQLAlchemy models updated: WatchedMovie.liked field + WatchlistMovie model
- Complete Letterboxd import pipeline: ZIP extraction, 5-CSV union merge by URI, TMDB resolution, DB writes with duplicate detection
- End-to-end verified with real Letterboxd export (import counts correct, duplicate protection confirmed, liked-but-not-watched handled)
- Hardened for production: file validation (size/format/zip bomb), TMDB rate limiting (~40 req/s), per-movie error isolation with DB session rollback

**Known tech debt:**
- `liked` field not exposed in tracking API responses (write-only via import)
- `WatchlistMovie` data has no read/CRUD API (write-only via import)
- Bulk import does not trigger taste profile rebuild
- `supabase db push` pending CLI auth (migrations verified correct at SQL level)

---

## v1.1 Letterboxd Integration Frontend (Shipped: 2026-03-12)

**Phases completed:** 3 phases, 4 plans
**Timeline:** 2 days (2026-03-10 → 2026-03-12)

**Delivered:** iOS users can import their Letterboxd history directly from the app — tap "Import from Letterboxd" in Profile, log into Letterboxd in an in-app webview, export data, and see import results without ever leaving BLND. Backend auto-rebuilds taste profile after import.

**Key accomplishments:**
- Backend taste rebuild hook fires automatically after successful Letterboxd import (BackgroundTasks)
- WKWebView bridge with download interception — captures ZIP without Safari redirect
- 4-state ImportContextView (loading/results/error/retry) for the full upload-to-results flow
- Multipart upload API via APIClient for ZIP file transfer
- Import button + instructions screen wired into ProfileView

**Tech debt resolved from v1.0:**
- Bulk import now triggers taste profile rebuild (BKND-01)

---

## v1.2 Revamp Other User Profile View (Shipped: 2026-03-12)

**Phases completed:** 3 phases, 5 plans
**Timeline:** 1 day (2026-03-12)
**Code:** ~990 lines added (484 backend, 506 iOS)

**Delivered:** Users see a rich friend profile with stats, watched movie poster grid, and tappable friends list — matching the depth of their own profile view.

**Key accomplishments:**
- 3 backend public profile endpoints (stats, watched movies, friends list) with friendship authorization gate
- TDD test scaffold for public profile endpoints with mock SQLAlchemy session
- PosterTile, StatsRow, PosterGrid extracted as shared SwiftUI components from ProfileView
- FriendProfileView rewritten (101 → 294 lines): parallel data loading, 3-column poster grid with infinite scroll, friends sheet with recursive navigation
- ProfileModels + ProfileAPI networking layer (5 Codable structs, 3 async methods)

**Known tech debt:**
- Blends count uses GroupMember query (may need adjustment as blends feature evolves)

---

