# Phase 1: Schema - Context

**Gathered:** 2026-03-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Add `liked` boolean column to `watched_movies` and create a new `watchlist_movies` table via Supabase migrations. Update SQLAlchemy models to match. No import logic — just schema.

</domain>

<decisions>
## Implementation Decisions

### watchlist_movies table design
- Columns: id (bigint identity PK), user_id (uuid), tmdb_id (int), added_date (date, nullable), created_at (timestamptz default now())
- FK: user_id references profiles(id) ON DELETE CASCADE
- FK: tmdb_id references movies(tmdb_id) — movie must be cached before adding to watchlist
- Constraint: UNIQUE(user_id, tmdb_id)
- added_date stores the date from Letterboxd's CSV (when user originally added to watchlist)

### liked column on watched_movies
- Type: boolean NOT NULL DEFAULT false
- All existing rows backfilled to false on migration
- Clean semantics: every watched movie has an explicit liked state

### Claude's Discretion
- WatchlistMovie model location (tracking/models.py is the natural home since it's tracking-adjacent)
- Exact migration file naming (follow existing convention: timestamp_descriptive_name.sql)

</decisions>

<specifics>
## Specific Ideas

- Follow existing watched_movies patterns exactly (same FK style, same cascade behavior, same id generation)
- Keep migrations as two separate SQL files or one combined — Claude decides based on convention

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-schema*
*Context gathered: 2026-03-03*
