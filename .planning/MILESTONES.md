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

