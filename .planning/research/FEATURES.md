# Feature Research

**Domain:** Letterboxd data import (CSV parsing + TMDB resolution + DB persistence)
**Researched:** 2026-03-03
**Confidence:** HIGH (based on actual Letterboxd export zip in project root, existing codebase inspection)

---

## CSV Format Reference (Verified from Real Export)

The following was derived by directly inspecting `letterboxd-arose3000-2026-03-04-03-09-utc.zip` in the project root — this is ground truth, not documentation.

### watched.csv

```
Date,Name,Year,Letterboxd URI
2024-12-29,The Matrix,1999,https://boxd.it/2a1m
2024-12-29,"The French Dispatch of the Liberty, Kansas Evening Sun",2021,https://boxd.it/jLP8
```

- `Date`: ISO 8601 date when entry was added to Letterboxd (not necessarily when watched)
- `Name`: Movie title — RFC 4180 quoted when it contains commas
- `Year`: 4-digit release year (string, not int in CSV)
- `Letterboxd URI`: Short URL like `https://boxd.it/2a1m` — NOT a TMDB ID

### ratings.csv

```
Date,Name,Year,Letterboxd URI,Rating
2024-12-29,The Matrix,1999,https://boxd.it/2a1m,4
2025-03-12,Hell or High Water,2016,https://boxd.it/bfGM,4.5
2025-03-23,Mamma Mia!,2008,https://boxd.it/1Tnq,0.5
```

- Superset of watched.csv — every rated movie is also watched
- `Rating`: float in 0.5 increments from 0.5 to 5.0. Whole numbers stored as integers (`4` not `4.0`). Half-stars stored as decimals (`4.5`). Matches DB check constraint exactly.
- Not all watched movies have ratings (watched.csv has more rows than ratings.csv)

### reviews.csv

```
Date,Name,Year,Letterboxd URI,Rating,Rewatch,Review,Tags,Watched Date
2026-03-04,A Minecraft Movie,2025,https://boxd.it/do4kz9,2,,Shit movie GGs,test,2026-03-03
```

- `Rating`: optional — can be empty string
- `Rewatch`: boolean-ish field — empty string or `true`
- `Review`: free text — can contain commas, quotes, newlines (RFC 4180 quoted)
- `Tags`: comma-separated tag list within one field — ambiguous parsing challenge (see Edge Cases)
- `Watched Date`: ISO 8601 date when user actually watched the film — distinct from `Date` (entry creation date)
- Note: The `Date` column here is when the review was written/logged on Letterboxd, `Watched Date` is the actual viewing date

### diary.csv

```
Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date
```

- Same as reviews.csv but **no Review column** — diary tracks viewings without written reviews
- `Tags` and `Watched Date` present
- A movie can appear multiple times in diary.csv if the user rewatched and logged it multiple times

### watchlist.csv

```
Date,Name,Year,Letterboxd URI
2024-12-29,The Truman Show,1998,https://boxd.it/18U8
```

- Same schema as watched.csv
- `Date` = when user added it to their watchlist
- Movies on watchlist have NOT been watched

### likes/films.csv

```
Date,Name,Year,Letterboxd URI
2024-12-29,Fight Club,1999,https://boxd.it/2a9q
```

- Same schema as watched.csv
- Represents films the user "hearted" on Letterboxd
- A liked film is usually (but not always) also in watched.csv

### profile.csv

```
Date Joined,Username,Given Name,Family Name,Email Address,Location,Website,Bio,Pronoun,Favorite Films
2024-12-29,arose3000,,,,,,,They / their,
```

- Single data row (header + 1 row)
- Most fields are optional/empty
- `Favorite Films` appears to be empty or a string representation

### deleted/ and orphaned/ directories

```
deleted/diary.csv   — header only, no data rows in this export
deleted/reviews.csv — header only, no data rows
orphaned/diary.csv  — header only, no data rows
orphaned/reviews.csv — header only, no data rows
```

- Headers match their non-deleted counterparts
- Represent entries Letterboxd could not associate with a film (orphaned) or user deleted
- In practice: likely always empty or near-empty

### likes/reviews.csv and likes/lists.csv

- Header only in this export (`Date` column only for lists)
- Represent reviews/lists the user liked (not films) — not relevant to import

---

## Edge Cases (Verified from Real Export)

| Edge Case | Example | Impact |
|-----------|---------|--------|
| Commas in movie titles | `"The French Dispatch of the Liberty, Kansas Evening Sun"` | Must use RFC 4180 CSV parser, not naive split |
| Apostrophes in titles | `Ferris Bueller's Day Off`, `O Brother, Where Art Thou?` | No escaping needed — apostrophes are fine |
| Parentheses in titles | `(500) Days of Summer` | TMDB search must handle leading punctuation |
| Ratings as integers vs floats | `4` vs `4.5` | Must coerce to float — `float("4")` works fine |
| Half-star minimum | `0.5` (Mamma Mia!) | DB constraint already handles 0.5-5.0 |
| Movie with no rating | Row in watched.csv but not ratings.csv | Import as watched with `rating=None` |
| Movie in reviews.csv with empty Rating | `Rating` field is empty string | Parse as `None`, not 0 |
| `Rewatch` field | Empty string or `true` | Not currently in schema — ignore or store as boolean |
| `Tags` field | `test` (single), potentially comma-separated | Not currently in schema — ignore for now |
| `Watched Date` vs `Date` | Different dates in reviews.csv | Use `Watched Date` (actual viewing), not `Date` (log entry creation) |
| Film in likes but not watched | Letterboxd allows liking without logging | Must handle creating watched entry to attach liked=true, or create a separate liked_films table |
| Film in diary multiple times | User watched + logged same film twice | Multiple diary rows per film — affects rewatch logic |
| Year is string in CSV | `"1999"` not `1999` | Must cast to int for TMDB search |
| Letterboxd URI is NOT TMDB ID | `https://boxd.it/2a1m` | Must use TMDB search-by-name+year to resolve |
| TMDB search ambiguity | Short titles, common names | Best match heuristic needed — see TMDB notes |
| Films with no TMDB match | Obscure films, short films, TV movies | Must handle gracefully — skip with logging |
| Zip structure | `likes/` subdirectory, `deleted/` subdirectory | Need `zipfile` module path handling, not naive file listing |

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features a Letterboxd import must have. Missing any = import is incomplete/broken.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Accept zip file upload | Letterboxd exports as zip — users just want to upload the file they downloaded | LOW | `zipfile` stdlib, read in-memory |
| Parse watched.csv | Core user history — everything else is enhancement | LOW | Standard CSV with RFC 4180 quoting |
| Parse ratings.csv | Ratings are the primary data that drives recommendations | LOW | Same schema + Rating column |
| Parse reviews.csv | Users write reviews specifically to preserve them | LOW | Additional Review + Tags + Watched Date columns |
| Parse watchlist.csv | "Want to watch" list is distinct and expected to transfer | LOW | Same schema as watched.csv |
| Parse likes/films.csv | "Heart" list is a distinct Letterboxd concept | LOW | Same schema as watched.csv |
| Resolve movie names to TMDB IDs | Letterboxd exports names, not TMDB IDs — resolution is required to store anything | MEDIUM | TMDB search endpoint, name+year lookup |
| Import watched movies | Primary history — without this, nothing else works | LOW | Insert to watched_movies, skip existing |
| Import ratings | Core user preference data | LOW | Float cast from CSV, attach to watched entry |
| Import reviews | Text reviews are high-value user content | LOW | Text field, attach to watched entry |
| Import watchlist | Conceptually separate from watched — needs own table | MEDIUM | Requires new watchlist_movies table + migration |
| Import liked films | Liked flag on watched entries | MEDIUM | Requires `liked` boolean on watched_movies + migration |
| Skip existing entries | Prevent overwriting manually entered data | LOW | Filter on existing (user_id, tmdb_id) before insert |
| Return import summary | User needs to know what happened — how many imported, how many skipped, how many failed | LOW | Return counts in response body |
| Handle TMDB resolution failures gracefully | Some movies won't resolve (obscure films, alternate titles) | LOW | Skip with count, log title+year |

### Differentiators (Competitive Advantage)

Features that go beyond what a basic import does.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Use `Watched Date` from reviews/diary (not `Date`) | Most tools use the log date — actual viewing date is more accurate and valuable for taste timeline | LOW | Reviews.csv has both columns; use `Watched Date` for watched_date field |
| Auto-cache movies in TMDB movies table | Other tools just store IDs; caching full movie data means recommendations are immediately available after import | MEDIUM | `get_movie_details` already does this — just wire it in |
| TMDB rate limit throttling | Large imports (100+ films) hit TMDB's ~40 req/s limit; throttling prevents failures | MEDIUM | `asyncio.sleep` between batches or semaphore |
| Detailed per-movie result in response | Return list of resolved/skipped/failed with title+reason, not just counts | LOW | Structured response helps user understand what didn't import |
| Handle liked-but-not-watched films | Letterboxd allows liking a film you haven't logged — a strict "liked requires watched" would silently drop these | MEDIUM | Create watched entry with `liked=True` and no other data, or skip with explanation |
| Rewatch detection from diary.csv | Diary has `Rewatch` flag and multiple entries — detect rewatches to show accurate view counts | HIGH | Requires schema changes (view count or multiple diary entries), scope risk |

### Anti-Features (Deliberately NOT Build)

| Anti-Feature | Why Requested | Why Avoid | Alternative |
|--------------|---------------|-----------|-------------|
| Re-import / incremental sync | "I want to keep Letterboxd and BLND in sync" | Massively complex: conflict resolution, deletion detection, drift handling. Wrong scope for v1. | Skip existing entries on re-upload — user can re-upload the zip later and new entries will be added |
| Diary.csv as primary source | Diary has richer data (Rewatch, Tags, Watched Date) | Diary and reviews.csv overlap with watched.csv. Using diary as primary creates duplication logic complexity. Watched.csv is the canonical watched list; diary is supplemental. | Parse watched.csv for the watched list; use reviews.csv for review text; ignore diary |
| Async background job processing | "Imports should be non-blocking" | True async with job queues (Celery, Arq, etc.) is significant infrastructure. Synchronous is fine for reasonable library sizes (under ~500 films). | Keep synchronous; if timeout is a problem, add streaming response later |
| Import Tags as first-class data | Tags appear in reviews.csv | Tags are Letterboxd-specific, not normalized, and not currently in the schema. Storing raw tag strings has no downstream value in BLND yet. | Ignore Tags column; add if BLND builds a tagging system later |
| Import Rewatch flag | Rewatch boolean appears in reviews/diary | No current schema support. Rewatch data is only meaningful with a multi-view tracking model. | Ignore Rewatch column; add if BLND builds a diary/rewatch feature |
| Import profile.csv | Profile has username, bio, pronouns | BLND users already have accounts. Overwriting BLND profile data with Letterboxd data is destructive and confusing. | Ignore profile.csv entirely |
| Import deleted/ and orphaned/ | "Why not import everything?" | Deleted entries were deleted for a reason. Orphaned entries have no valid film association. Both are Letterboxd internal bookkeeping. | Ignore these directories |
| Import likes/reviews.csv and likes/lists.csv | These appear in the zip | These are reviews/lists OTHER users wrote that this user liked — not their own data, not useful for BLND. | Ignore |
| Frontend import UI | Nice for end users | Out of scope per PROJECT.md — backend only endpoint | Document the POST /import/letterboxd API contract for future frontend work |

---

## Feature Dependencies

```
[Zip extraction]
    └──requires──> [CSV parsing — watched.csv]
                       └──requires──> [TMDB name+year resolution]
                                          └──requires──> [Movie caching via get_movie_details]
                                                             └──requires──> [watched_movies INSERT]

[ratings.csv parsing] ──enhances──> [watched_movies INSERT] (attaches rating)
[reviews.csv parsing] ──enhances──> [watched_movies INSERT] (attaches review + watched_date)

[likes/films.csv parsing]
    └──requires──> [liked boolean on watched_movies] (migration)
    └──requires──> [watched_movies INSERT] (entry must exist to set liked=true)

[watchlist.csv parsing]
    └──requires──> [watchlist_movies table] (migration)
    └──requires──> [TMDB name+year resolution]

[TMDB resolution]
    └──requires──> [TMDB rate limit handling] (for imports > ~40 films)
```

### Dependency Notes

- **TMDB resolution requires movie caching:** `get_movie_details` already handles caching as a side effect. Every resolved film will be in the `movies` table before the watched_movies insert, satisfying the FK constraint.
- **liked flag requires watched entry:** If a film appears in likes/films.csv but NOT in watched.csv, we cannot set liked=true on a non-existent watched_movies row. Decision: create the watched entry with only liked=true (no rating, no review, no watched_date), or skip. Skipping loses data; creating is semantically odd. **Recommended: create watched entry with liked=true and null other fields.**
- **ratings.csv and reviews.csv are both subsets of watched.csv:** Parse watched.csv first for the master list. Then enrich from ratings.csv and reviews.csv. Do not use ratings.csv or reviews.csv as the source of truth for the watched list — they are supplemental.
- **watchlist is independent of watched:** Watchlist movies are not watched, so they do not go into watched_movies. They require a separate table.

---

## MVP Definition

### Launch With (v1)

Minimum to make the import feature useful and correct.

- [ ] Zip extraction and CSV file discovery — accepts upload, finds expected CSVs
- [ ] Parse watched.csv — master watched list
- [ ] Parse ratings.csv — enrich watched entries with ratings
- [ ] Parse reviews.csv — enrich watched entries with review text and actual watched_date
- [ ] Parse watchlist.csv — separate watchlist import (requires migration)
- [ ] Parse likes/films.csv — set liked=true on watched entries (requires migration)
- [ ] TMDB name+year resolution with graceful skip on failure
- [ ] Skip existing (user_id, tmdb_id) entries — no overwrite
- [ ] Return structured summary: imported count, skipped count, failed count, failed titles

### Add After Validation (v1.x)

- [ ] TMDB rate limit throttling — add when real-world imports expose timeout issues
- [ ] Per-movie result detail in response — add when users report not knowing what failed

### Future Consideration (v2+)

- [ ] Re-import / incremental update — only after core import is validated at scale
- [ ] Rewatch tracking from diary.csv — only if BLND builds a multi-view diary model
- [ ] Tags import — only if BLND builds a tagging system
- [ ] Async job processing — only if synchronous times out for large libraries (500+ films)

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Zip upload + CSV extraction | HIGH | LOW | P1 |
| watched.csv parsing + TMDB resolution | HIGH | MEDIUM | P1 |
| ratings.csv parsing | HIGH | LOW | P1 |
| reviews.csv parsing (with Watched Date) | HIGH | LOW | P1 |
| Skip existing entries | HIGH | LOW | P1 |
| Import summary response | MEDIUM | LOW | P1 |
| watchlist.csv parsing | HIGH | LOW | P1 |
| likes/films.csv + liked migration | MEDIUM | MEDIUM | P1 |
| TMDB rate limit throttling | HIGH | LOW | P2 |
| Per-movie result detail in response | MEDIUM | LOW | P2 |
| diary.csv rewatch tracking | LOW | HIGH | P3 |
| Tags import | LOW | MEDIUM | P3 |
| Async job processing | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

---

## Competitor Feature Analysis

There is no direct competitor product (other Letterboxd-to-X importers exist for Trakt, Plex, etc. but serve different target systems). The relevant comparison is between approaches taken by community import scripts.

| Feature | Community Python Scripts | Trakt Importer Tools | Our Approach |
|---------|--------------------------|---------------------|--------------|
| CSV source | watched.csv or diary.csv | Typically ratings.csv | watched.csv as master, ratings/reviews as enrichment |
| TMDB resolution | Name search, some use year | Name search | Name + year search, skip on failure |
| Duplicate handling | Varies — some overwrite | Skip or update | Always skip existing |
| Liked films | Rarely implemented | Not applicable | liked boolean on watched_movies |
| Watchlist | Sometimes | Separate list | Separate watchlist_movies table |
| Rate limiting | Rarely handled | Sometimes | Explicit throttle for >40 req/s |
| Error reporting | Usually silent | Summary counts | Summary counts + failed title list |

---

## Sources

- Direct inspection of `letterboxd-arose3000-2026-03-04-03-09-utc.zip` in project root (HIGH confidence — ground truth from real export)
- `/Users/adamrose/Desktop/blnd/.planning/PROJECT.md` — project requirements and constraints (HIGH confidence)
- `/Users/adamrose/Desktop/blnd/blnd_backend/app/tracking/models.py` — WatchedMovie schema (HIGH confidence)
- `/Users/adamrose/Desktop/blnd/blnd_backend/app/movies/services.py` — `get_movie_details` caching behavior (HIGH confidence)
- `/Users/adamrose/Desktop/blnd/blnd_backend/CLAUDE.md` — TMDB rate limit (~40 req/s), existing architecture (HIGH confidence)
- Training knowledge for Letterboxd CSV format corroboration and community importer patterns (MEDIUM confidence — confirmed against real export)

---

*Feature research for: Letterboxd CSV import into BLND backend*
*Researched: 2026-03-03*
