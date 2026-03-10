# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — Letterboxd Import

**Shipped:** 2026-03-09
**Phases:** 3 | **Plans:** 6

### What Was Built
- Supabase migrations: `liked` column on watched_movies + `watchlist_movies` table
- SQLAlchemy models: WatchedMovie.liked + WatchlistMovie
- Complete Letterboxd import pipeline: ZIP extraction, 5-CSV union merge by URI, TMDB resolution, DB writes
- Production hardening: file validation (size/format/zip bomb), TMDB rate limiting, per-movie error isolation

### What Worked
- Single-phase core workflow: keeping CSV parsing, TMDB resolution, and DB writes together avoided subset-assumption bugs
- URI-keyed union merge pattern: correctly captured films across all 5 CSVs without duplication
- Query-first duplicate detection: cleaner than IntegrityError catch, enables accurate skip counting
- End-to-end verification plan (02-03) caught real issues before hardening phase
- Migrations-first sequencing: schema was stable before any import code was written

### What Was Inefficient
- blnd_backend/ as a separate git sub-repo created confusion with commit tracking in SUMMARY files
- Phase 3 ROADMAP.md checkbox not updated to [x] after execution — manual tracking lag
- TMDB rate limiting applied unconditionally (even after cache hits) — slightly slower than necessary but safe

### Patterns Established
- Single-concern ALTER per migration file (one column per migration)
- Supabase migration naming: `{timestamp}_{descriptive_name}.sql`
- `_get_or_create` pattern for URI-keyed merge dicts
- `server_default` uses SQL string value (`"false"`) not Python literal for DB-side defaults
- `db.rollback()` as first statement in exception handlers to prevent dirty-session cascading

### Key Lessons
1. When multiple CSVs describe the same entities (films), merge by stable identifier (URI) first, then process the unified set. Never process CSVs independently.
2. TMDB uses `primary_release_year` (not `year`) as the search parameter — API docs are the source of truth, not intuition.
3. Liked-but-not-watched films need special handling: create a watched_movies entry with `liked=true` and null everything else.
4. Writing data without a read path creates invisible tech debt — plan API exposure alongside data import.

### Cost Observations
- Model mix: balanced profile (sonnet for agents, opus for orchestration)
- Notable: 6 plans completed in ~15 min total execution time — high velocity for a complete feature

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 3 | 6 | Initial milestone — established migration-first, single-phase-core pattern |

### Top Lessons (Verified Across Milestones)

1. (First milestone — lessons above are candidates for cross-validation in future milestones)
