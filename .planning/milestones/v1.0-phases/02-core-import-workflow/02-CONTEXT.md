# Phase 2: Core Import Workflow - Context

**Gathered:** 2026-03-04
**Status:** Ready for planning

<domain>
## Phase Boundary

The `POST /import/letterboxd` endpoint accepts a Letterboxd zip file, parses 5 CSVs (ratings, reviews, watched, watchlist, likes/films), resolves each movie to a TMDB ID, and writes the data to the user's account. Returns a structured summary. All logic in `app/import_data/workflows.py`.

</domain>

<decisions>
## Implementation Decisions

### TMDB match strategy
- Use first result from TMDB search (trust TMDB's relevance ranking)
- Search by name + year as provided in CSV
- If zero results: skip the movie and include its title in the "failed" list in the response
- No retry without year — single search attempt per movie
- Basic title verification: confirm the TMDB result title contains at least some words from the Letterboxd title before accepting the match

### Merge & conflict rules
- Union all CSVs by Letterboxd URI — films appearing in any file are captured
- Ratings in ratings.csv and reviews.csv should always be the same; use whichever is available (no priority needed)
- watched_date: use `Watched Date` from reviews.csv when available, fall back to `Date` from watched.csv
- Liked films not in watched.csv: create a watched_movies entry with liked=true, null rating, null review, null watched_date
- Watchlist entries go to watchlist_movies table (separate from watched_movies)

### Claude's Discretion
- Endpoint contract details (auth requirement, file size limits, content-type handling)
- Import response shape (exact JSON structure for counts and failed titles)
- Internal data structure for the union merge (dict keyed by URI, etc.)
- Order of CSV processing

</decisions>

<specifics>
## Specific Ideas

- The existing `get_movie_details` already handles TMDB fetch + movie caching — reuse it for each resolved movie
- The existing stub endpoint at `POST /import/letterboxd` in `views.py` should be wired to the workflow
- All changes must be committed to `arose/letterboxdIntegration` branch in `blnd_backend/`

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-core-import-workflow*
*Context gathered: 2026-03-04*
