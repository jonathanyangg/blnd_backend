"""Semantic discover pipeline — LLM-titles primary, pgvector hybrid.

Phase 1 MVP: LLM title generation → batched DB lookup → cache.
"""

import hashlib
import json
import logging

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.config import settings
from app.movies.models import Movie
from app.recommendations.ranking import to_match_percentage
from app.recommendations.services import get_hidden_movie_ids, get_top_rated_movies

logger = logging.getLogger(__name__)

LLM_MODEL = "gpt-4.1-nano"
LLM_MAX_TITLES = 30

SYSTEM_PROMPT = """You are a film curator with encyclopedic movie knowledge. Given a user's \
natural-language query, return the BEST matching movies as strict JSON:
{"movies": [{"title": "<canonical English title>", "year": <int>, \
"why": "<one-sentence reason it matches>"}]}

Return exactly 30 movies, best first.

Rules:
- REAL movies only. No hallucinations. Use the theatrical release year.
- Match the user's INTENT — tone, pacing, narrative structure, mood — not just topic.
- Be strict about compositional queries: if they say "like X but Y", actually apply Y.
- Prefer widely-rated films (TMDB vote_count >= 100).
- No short films, no TV series.
- If the query is vague, lean into canon + variety."""


def query_hash(query: str) -> str:
    normalized = query.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _get_openai_client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def get_cached_result(
    user_id: str, qhash: str, db: Session
) -> tuple[list[int], dict[int, str]] | None:
    """Return (tmdb_ids, reasoning_map) from cache if fresh, else None."""
    row = db.execute(
        text(
            "SELECT result_tmdb_ids, reasoning_map FROM semantic_search_cache "
            "WHERE user_id = :uid AND query_hash = :qh AND expires_at > now() "
            "LIMIT 1"
        ),
        {"uid": user_id, "qh": qhash},
    ).first()
    if row is None:
        return None
    # JSON keys are strings — convert back to int
    reasoning = {int(k): v for k, v in dict(row[1]).items()}
    return list(row[0]), reasoning


def write_cache(
    user_id: str,
    qhash: str,
    query_text: str,
    tmdb_ids: list[int],
    reasoning_map: dict[int, str],
    db: Session,
) -> None:
    db.execute(
        text(
            "INSERT INTO semantic_search_cache "
            "(user_id, query_hash, query_text, result_tmdb_ids, reasoning_map) "
            "VALUES (:uid, :qh, :qt, :ids, :rm) "
            "ON CONFLICT (user_id, query_hash) DO UPDATE SET "
            "result_tmdb_ids = EXCLUDED.result_tmdb_ids, "
            "reasoning_map = EXCLUDED.reasoning_map, "
            "created_at = now(), "
            "expires_at = now() + interval '24 hours'"
        ),
        {
            "uid": user_id,
            "qh": qhash,
            "qt": query_text,
            "ids": tmdb_ids,
            "rm": json.dumps(reasoning_map),
        },
    )
    db.commit()


# ---------------------------------------------------------------------------
# LLM title generation
# ---------------------------------------------------------------------------


def generate_title_suggestions(
    query: str, user_favorites: list[str] | None = None
) -> list[dict]:
    """Call OpenAI to get ~30 movie title suggestions.

    Returns list of {"title": str, "year": int, "why": str}.
    Catches all LLM/network errors and returns empty list (no 500).
    """
    user_msg = f"Query: {query}"
    if user_favorites:
        user_msg += f"\n\nUser's favorites: {', '.join(user_favorites[:5])}"

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=LLM_MODEL,
            max_tokens=2000,
            timeout=30,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
        )
    except Exception:
        logger.exception("LLM call failed for query: %s", query[:100])
        return []

    raw = response.choices[0].message.content or ""
    try:
        parsed = json.loads(raw)
        return parsed.get("movies", [])[:LLM_MAX_TITLES]
    except json.JSONDecodeError:
        logger.error("Failed to parse LLM response: %s", raw[:500])
        return []


# ---------------------------------------------------------------------------
# Batched DB lookup
# ---------------------------------------------------------------------------


def batched_movie_lookup(
    suggestions: list[dict], db: Session
) -> tuple[list[Movie], dict[int, str]]:
    """Look up suggested titles in the movies table.

    Uses case-insensitive title match with ±1 year tolerance.
    Returns (matched_movies, reasoning_map: {tmdb_id: why}).
    """
    if not suggestions:
        return [], {}

    # Build OR conditions for each suggestion
    conditions = []
    params: dict = {}
    for i, sug in enumerate(suggestions):
        title = sug.get("title", "")
        year = sug.get("year")
        if not title:
            continue
        conditions.append(
            f"(lower(m.title) = :t{i} AND m.year BETWEEN :y{i}lo AND :y{i}hi)"
        )
        params[f"t{i}"] = title.lower()
        params[f"y{i}lo"] = (year - 1) if year else 1900
        params[f"y{i}hi"] = (year + 1) if year else 2099

    if not conditions:
        return [], {}

    sql = f"SELECT tmdb_id FROM movies m WHERE {' OR '.join(conditions)}"
    rows = db.execute(text(sql), params).fetchall()
    matched_ids = [row[0] for row in rows]

    if not matched_ids:
        return [], {}

    movies = db.query(Movie).filter(Movie.tmdb_id.in_(matched_ids)).all()
    movie_by_title = {m.title.lower(): m for m in movies}

    # Build reasoning map preserving LLM rank order
    reasoning_map: dict[int, str] = {}
    ordered_movies: list[Movie] = []
    for sug in suggestions:
        title_lower = sug.get("title", "").lower()
        movie = movie_by_title.get(title_lower)
        if movie and movie.tmdb_id not in reasoning_map:
            reasoning_map[movie.tmdb_id] = sug.get("why", "")
            ordered_movies.append(movie)

    return ordered_movies, reasoning_map


# ---------------------------------------------------------------------------
# Personalization rerank (lightweight, in-memory)
# ---------------------------------------------------------------------------


def personalize_rerank(
    movies: list[Movie],
    reasoning_map: dict[int, str],
    _profile: Profile,
) -> list[dict]:
    """Rerank movies blending LLM rank with user taste similarity.

    Phase 1: LLM rank only. Phase 2 will add cosine with taste embeddings.
    """
    if not movies:
        return []

    results = []
    n = len(movies)
    for rank, movie in enumerate(movies):
        # LLM rank score: linear decay from 1.0 to ~0.3
        llm_score = 1.0 - (rank / n) * 0.7
        score = 0.70 * llm_score

        results.append(
            {
                "tmdb_id": movie.tmdb_id,
                "title": movie.title,
                "year": movie.year,
                "overview": movie.overview,
                "poster_path": movie.poster_path,
                "genres": movie.genres or [],
                "runtime": movie.runtime,
                "vote_average": round(movie.vote_average / 2, 1)
                if movie.vote_average
                else None,
                "trailer_url": movie.trailer_url,
                "director": movie.director,
                "cast": movie.cast or [],
                "tagline": movie.tagline,
                "backdrop_path": movie.backdrop_path,
                "match_score": round(to_match_percentage(score), 4),
                "match_reasoning": reasoning_map.get(movie.tmdb_id, ""),
            }
        )

    return results


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_semantic_discover(
    query: str,
    user_id: str,
    profile: Profile,
    db: Session,
    exclude_ids: list[int] | None = None,
    limit: int = 30,
) -> dict:
    """Top-level orchestrator for semantic discover.

    1. Check cache
    2. If miss: LLM → batched lookup → cache write
    3. Fetch movies, apply exclusions, rerank, return
    """
    qhash = query_hash(query)
    exclude_set = set(exclude_ids or [])

    # Only exclude hidden movies + client-provided exclude list.
    # Watched and watchlisted movies are NOT excluded — semantic search
    # is intent-based, so showing known-good matches is expected.
    # Swipe signals are not hides: `not_for_me` stays searchable.
    # See docs/swipe-signals.md.
    hidden_ids = set(get_hidden_movie_ids(user_id, db))
    all_exclude = exclude_set | hidden_ids

    # 1. Check cache
    cached = get_cached_result(user_id, qhash, db)
    if cached:
        cached_ids, cached_reasoning = cached
        # Filter exclusions from cached results
        filtered_ids = [tid for tid in cached_ids if tid not in all_exclude][:limit]
        if filtered_ids:
            movies = db.query(Movie).filter(Movie.tmdb_id.in_(filtered_ids)).all()
            movie_map = {m.tmdb_id: m for m in movies}
            ordered = [movie_map[tid] for tid in filtered_ids if tid in movie_map]
            results = personalize_rerank(ordered, cached_reasoning, profile)
            return {"query": query, "results": results}

    # 2. LLM title generation
    user_favorites = None
    top_rated = get_top_rated_movies(user_id, db, limit=5)
    if top_rated:
        user_favorites = [
            f"{m['title']} ({m['year']})" for m in top_rated if m.get("title")
        ]

    suggestions = generate_title_suggestions(query, user_favorites)
    if not suggestions:
        return {"query": query, "results": []}

    # 3. Batched DB lookup
    movies, reasoning_map = batched_movie_lookup(suggestions, db)

    # 4. Cache the result (before exclusions, so cache is reusable)
    all_result_ids = [m.tmdb_id for m in movies]
    if all_result_ids:
        write_cache(user_id, qhash, query, all_result_ids, reasoning_map, db)

    # 5. Apply exclusions
    movies = [m for m in movies if m.tmdb_id not in all_exclude][:limit]

    # 6. Rerank + format
    results = personalize_rerank(movies, reasoning_map, profile)
    return {"query": query, "results": results}
