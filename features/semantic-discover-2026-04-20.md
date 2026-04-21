# Semantic Discover (AI Search)

**Status:** draft — not implemented
**Owner:** jonathan
**Premium:** yes (402 for non-premium)

---

## Goal

Let premium users search the catalog with natural-language intent queries — "slow burn thriller with unreliable narrator", "like Parasite but funnier", "cozy movies that feel like a warm hug" — and get back a curated list of movies that actually match the intent, not just the topic.

The iOS entry point is a "Search with AI" button on Discover. Non-premium hits the paywall.

---

## Approach: LLM-titles primary, pgvector hybrid

We validated this empirically against the live DB with 5 canonical queries. LLM-titles crushes pgvector-first on every compositional query. See **Validation** below.

### Pipeline

```
query
  └─► LLM call #1 (Haiku 4.5 or GPT-4o)
        "Return 30 real movies matching this query as {title, year, why} JSON.
         User's top-rated films: <5 titles from their watched history>"
        ───► ~30 titles
  └─► Batched DB lookup
        SELECT * FROM movies WHERE (lower(title), year ∈ {y-1, y, y+1}) IN (...)
        ───► ~25-30 hits out of 30
  └─► For misses (0-5): on-demand TMDB search + cache (fire-and-forget, best-effort)
  └─► Recency booster (pgvector)
        avg(top 5 LLM hits' embeddings) → match_movies(vector, 50)
        filter: year >= current_year - 2, vote_count >= 50
        ───► +5-10 post-cutoff picks
  └─► Personalization rerank
        final = 0.70·llm_rank + 0.20·cos(user_positive) − 0.15·cos(user_negative)
        respects user's taste without overriding intent
  └─► Apply exclusions: watched ∪ hidden ∪ watchlist ∪ client-provided `exclude` list
  └─► Return top N with match_reasoning from LLM's `why`
```

### Why this beats pure embedding
- Embeddings of short queries live in a different manifold than 200-word overviews — weak recall on compositional/abstract queries.
- LLMs have encyclopedic movie knowledge and handle composition natively ("X but funnier").
- Overviews are plot-focused; queries are tone/vibe-focused. Mismatch.

### Why we still use pgvector
1. **Recency gap** — LLM doesn't know 2025-2026 films well. Nearest-neighbor to LLM hits surfaces post-cutoff releases.
2. **Personalization** — cosine against user's taste vectors re-ranks within the intent-matched set.
3. **Soft negative penalty** — existing `negative_embedding` still filters out things close to known dislikes.

---

## Validation (live DB, 2026-04-20)

Ran both approaches against 5 queries. Scores = canon coverage, vibes-check:

| Query | Embedding pipeline | LLM-titles |
|-------|---|---|
| slow burn thriller w/ unreliable narrator | 6/10 | **10/10** |
| like Parasite but funnier | 3/10 | **9/10** |
| quiet Japanese movies about grief | 8/10 | **10/10** |
| mind-bending sci-fi | 2/10 | **10/10** |
| cozy movies that feel like a warm hug | 4/10 | **10/10** |

**DB hit rate** for LLM-titles: 92% average (100% on 2 of 5, lowest was 73% on Japanese grief where LLM returned titles with non-English variants our DB indexes under different strings).

Test scripts preserved:
- `scripts/test_semantic_search.py` — embedding-first approach
- `scripts/test_llm_titles.py` — LLM-titles approach

---

## Latency budget

Current measured (gpt-4o-mini, 30 per-title SQL queries):
- Expand/generate: 14-20s (model bottleneck)
- Lookup: 2-8s (N+1 problem)
- Total: 14-24s

Target for production:
- LLM: 3-5s (Haiku 4.5 or GPT-4o, not mini)
- Batched SQL lookup: <100ms
- Recency booster pgvector: <300ms
- Personalization rerank: <50ms (in-memory)
- **Target total: 5-7s**

If still too slow: stream the response (return LLM hits first, then stream recency booster + personalization pass). FE shows the first 20 cards immediately.

---

## Cost

Per query (estimate, GPT-4o):
- Input: ~400 tokens (system + query + user taste context)
- Output: ~1000 tokens (30 titles with `why`)
- ~$0.01-0.03 per query

At 20 queries/day/premium user: ~$0.60/user/month — fits comfortably in premium pricing.

If we use Haiku 4.5 instead: ~$0.003-0.008 per query. Probably the right default.

---

## API shape

```
POST /recommendations/semantic-discover
Body:
  {
    "query": str,          # required, 3-200 chars
    "limit": int = 30,     # 10-50
    "exclude": list[int] = []  # seen tmdb_ids for infinite scroll
  }

Response: SemanticSearchResponse
  {
    "query": str,
    "results": [
      {
        ...standard movie fields (tmdb_id, title, year, poster_path, etc.),
        "match_score": float,
        "match_reasoning": str   # the LLM's "why"
      }
    ]
  }

Status codes:
  200 — results
  402 — not premium (use existing is_premium(profile) check)
  429 — rate limit hit
```

---

## Rate limiting

Tighter than default because every request hits an LLM:

```python
# app/core/rate_limit.py
LIMIT_AI_SEARCH = "20/hour"  # per premium user
```

Also: cache result by `(user_id, normalized_query_hash)` for 24h so infinite-scroll and repeated queries don't re-burn LLM calls.

---

## Caching

New migration: `semantic_search_cache` table.

```sql
CREATE TABLE semantic_search_cache (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    query_hash text NOT NULL,         -- sha256(lower(trim(query)))
    query_text text NOT NULL,
    result_tmdb_ids integer[] NOT NULL,
    reasoning_map jsonb NOT NULL,     -- { "tmdb_id": "match reasoning text", ... }
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now() + interval '24 hours'
);

CREATE UNIQUE INDEX idx_semantic_cache_user_query
    ON semantic_search_cache(user_id, query_hash);

CREATE INDEX idx_semantic_cache_expires
    ON semantic_search_cache(expires_at);
```

Pagination/infinite scroll slices the cached `result_tmdb_ids` by `exclude` list; no re-call.

---

## Files to create / touch

### New

- `app/recommendations/semantic_search.py` — core module
  - `generate_title_suggestions(query, user_context)` → LLM call #1
  - `batched_movie_lookup(suggestions, db)` → single SQL, title+year match with ±1 year tolerance
  - `fetch_missing_from_tmdb(misses, db, tmdb_client)` → fire-and-forget cache fill
  - `recency_booster(seed_embeddings, db)` → pgvector pass over recent films
  - `personalize_rerank(candidates, user_positive, user_negative)` → rerank
  - `run_semantic_discover(query, user, db)` → top-level orchestrator

- `app/recommendations/schemas.py` — add
  - `SemanticSearchRequest`
  - `SemanticSearchResponse`
  - `SemanticSearchResultItem` (extends movie fields with `match_reasoning`)
  - `LLMSuggestion` (internal: title, year, why)

- `supabase/migrations/<ts>_semantic_search_cache.sql` — cache table

### Touch

- `app/recommendations/views.py` — add `POST /me/semantic-discover`
  - Auth required, premium gate via `is_premium(profile)` returns 402
  - Rate limited with `LIMIT_AI_SEARCH`
  - Check cache first, else run pipeline, else cache result

- `app/core/rate_limit.py` — add `LIMIT_AI_SEARCH = "20/hour"`

- `main.py` — nothing to change (router already registered)

- `CLAUDE.md` — flip "In Flight" bullet on semantic discover to "Done" once shipped

---

## LLM prompt (draft)

### Title generation (call #1)

```
System:
You are a film curator with encyclopedic movie knowledge. Given a user's
natural-language query, return the BEST matching movies as strict JSON:
{"movies": [{"title": "<canonical English title>", "year": <int>,
"why": "<one-sentence reason it matches>"}]}

Return exactly 30 movies, best first.

Rules:
- REAL movies only. No hallucinations. Use the theatrical release year.
- Match the user's INTENT — tone, pacing, narrative structure, mood — not
  just topic.
- Be strict about compositional queries: if they say "like X but Y",
  actually apply Y.
- Prefer widely-rated films (TMDB vote_count >= 100).
- No short films, no TV series.
- If the query is vague, lean into canon + variety.

User:
Query: {query}

[Optional context]
User's favorites: {top 5 rated titles, if available}
User's disliked genres: {low-rated genres, if signal is strong}
```

### Why we do NOT do a second rerank LLM call
Empirically, the LLM's first-shot ordering was solid. A second rerank pass adds 3-5s latency for marginal gain. Skip it. The personalization rerank (lightweight, in-memory) handles post-hoc reordering.

---

## Edge cases

- **Query too short / garbage** — reject client-side if < 3 chars. Backend: if LLM returns 0 valid titles, return empty results, don't cache.
- **Zero hits in DB** — fall back to pgvector on the raw query embedding with relaxed thresholds. Rare given 92% hit rate.
- **User on free tier** — 402 before any work. No LLM call.
- **User has no taste embedding yet** — skip personalization rerank, use pure LLM order.
- **Concurrent requests** — per-user rate limit handles it; cache write uses `ON CONFLICT DO UPDATE`.
- **LLM hallucinates a title** — gets dropped by the DB lookup. Net effect: result list is 1 shorter. Acceptable.
- **LLM JSON parse fails** — retry once with stricter prompt; if still fails, 500 with clear error.

---

## Phased rollout

### Phase 1 — MVP (2-3 days)
1. Migration for `semantic_search_cache`
2. `semantic_search.py` with just: LLM call + batched lookup + cache
3. Endpoint + premium gate + rate limit
4. Ship. Validate quality on real user queries.

### Phase 2 — quality polish (1-2 days)
1. Recency booster (pgvector nearest-neighbor to LLM hits)
2. TMDB fallback fetch for misses
3. Personalization rerank with user's taste embeddings
4. Pass user's top-rated titles into the LLM prompt

### Phase 3 — latency (1 day)
1. Switch to streaming response (SSE), FE renders first batch immediately
2. Benchmark Haiku 4.5 vs GPT-4o; pick winner

### Phase 4 — analytics
1. Log every query (with consent) to feed future fine-tuning
2. Track: CTR on results, track rate, watchlist rate per query type
3. Use `source='semantic_discover'` on watched/watchlist writes for attribution

---

## Open questions

1. **Anthropic vs OpenAI for the LLM call?** Haiku 4.5 is cheaper + faster. GPT-4o has broader film knowledge in some corners. Worth a side-by-side on same 10 queries before committing. Need to add `ANTHROPIC_API_KEY` to `.env` if we go Haiku.
2. **Should cache be per-user or global?** Per-user is simpler and respects personalization. Global would save cost but requires a separate post-hoc personalization pass on cache hits. Start per-user.
3. **How hard is the 402 for free users — paywall copy, upgrade CTA?** FE concern, not backend.
4. **Log queries for analytics?** Yes, but scrub to remove PII before training or sharing.

---

## Not doing (explicitly)

- **Second-pass LLM rerank on top 50** — nice on paper, empirically unneeded, adds 3-5s for marginal gain. Revisit if quality complaints surface.
- **Blending user taste into positive embedding** — for intent search, the user has already overridden their taste by typing a query. Only apply taste as soft rerank + negative penalty.
- **Streaming LLM response token-by-token** — complicates the pipeline; cache + SSE boundary (send batch 1 → then batch 2) is simpler and achieves the same perceived latency.

---

*Last updated: 2026-04-20*
