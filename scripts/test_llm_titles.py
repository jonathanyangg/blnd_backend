"""Test the 'just ask an LLM for titles' approach.

Flow:
  1. One LLM call: "give me 30 movies matching '{query}'" → JSON list of {title, year, why}
  2. Lookup each in movies table (title + year match, fuzzy year ±1)
  3. Report: hit rate, missing titles, final list
"""

import json
import sys
import time

from sqlalchemy import func, or_

from app.database import SessionLocal
from app.dependencies import openai_client
from app.movies.models import Movie

N_TITLES = 30

SYSTEM = (
    "You are a film curator with encyclopedic movie knowledge. Given a user's "
    "natural-language query, return the BEST matching movies as strict JSON: "
    '{"movies": [{"title": "<exact title>", "year": <int>, '
    '"why": "<one sentence on why it matches>"}]}. '
    f"Return exactly {N_TITLES} movies, best first. "
    "Rules: Return REAL movies only — no hallucinations. Use the canonical "
    "English title. Use the theatrical release year. Match the user's INTENT "
    "(tone, pacing, structure, mood), not just the topic. Be compositional: "
    "if they say 'like X but Y', actually apply Y. Prefer widely-rated films "
    "(vote_count >= 100 on TMDB). Do not include short films or TV series."
)


def ask_llm(query: str) -> list[dict]:
    r = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": query},
        ],
        response_format={"type": "json_object"},
        max_tokens=2000,
        temperature=0.3,
    )
    raw = r.choices[0].message.content or "{}"
    return json.loads(raw).get("movies", [])


def lookup_movie(title: str, year: int | None, db) -> Movie | None:
    """Case-insensitive title match, year ±1 tolerance."""
    q = db.query(Movie).filter(func.lower(Movie.title) == title.lower())
    if year:
        q = q.filter(
            or_(Movie.year == year, Movie.year == year - 1, Movie.year == year + 1)
        )
    return q.first()


def run_query(query: str, db) -> None:
    print("\n" + "=" * 80)
    print(f"QUERY: {query}")
    print("=" * 80)

    t0 = time.time()
    suggestions = ask_llm(query)
    t1 = time.time()
    print(f"[llm {t1 - t0:.2f}s] {len(suggestions)} suggestions returned")

    hits: list[tuple[dict, Movie]] = []
    misses: list[dict] = []
    for s in suggestions:
        title = s.get("title", "")
        year = s.get("year")
        if not title:
            continue
        movie = lookup_movie(title, year, db)
        if movie:
            hits.append((s, movie))
        else:
            misses.append(s)

    hit_rate = len(hits) / max(len(suggestions), 1)
    print(
        f"[lookup {time.time() - t1:.2f}s] {len(hits)}/{len(suggestions)} "
        f"in DB ({hit_rate:.0%} hit rate), {len(misses)} missing"
    )

    print(f"\nTOTAL LATENCY: {time.time() - t0:.2f}s\n")

    print("HITS:")
    for i, (s, m) in enumerate(hits[:15], 1):
        print(f"  {i:2}. {m.title} ({m.year}) [vote={m.vote_average}]")
        print(f"      why: {s.get('why', '')}")

    if misses:
        print(f"\nMISSES ({len(misses)}):")
        for s in misses:
            print(f"  - {s.get('title')} ({s.get('year')})")


QUERIES = [
    "slow burn thriller with unreliable narrator",
    "like Parasite but funnier",
    "quiet Japanese movies about grief",
    "mind-bending sci-fi that makes you question reality",
    "cozy movies that feel like a warm hug",
]


def main() -> None:
    queries = sys.argv[1:] if len(sys.argv) > 1 else QUERIES
    db = SessionLocal()
    try:
        for q in queries:
            run_query(q, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
