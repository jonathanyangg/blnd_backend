"""Quick end-to-end test of the semantic search pipeline.

Flow per query:
  1. GPT-4o-mini expands query → fake movie synopsis (ideal_overview)
  2. text-embedding-3-small embeds the synopsis
  3. match_movies RPC returns top-200 by cosine
  4. Filter runtime>=45, vote>=5.5, drop music/documentary
  5. First-pass rerank: 0.85·cos + 0.15·consensus, keep top-30
  6. GPT-4o-mini reranks top-30, returns top-10 with one-line reasoning
"""

import json
import sys
import time

from sqlalchemy import text

from app.database import SessionLocal
from app.dependencies import openai_client
from app.movies.models import Movie

POOL_SIZE = 200
RERANK_POOL = 30
FINAL_N = 10

EXPAND_SYSTEM = (
    "You are a movie description writer. Given a user's natural-language search "
    "query, write a fictional 2-3 paragraph movie overview/synopsis that perfectly "
    "captures the themes, genres, tone, pacing, and storytelling style described. "
    "Write it exactly like a TMDB movie plot summary — with characters, a setting, "
    "and a narrative arc. Do NOT describe the query or the user. Describe the "
    "IDEAL movie matching the query."
)

RERANK_SYSTEM = (
    "You are a film curator. You will receive a user's search query and a numbered "
    "list of candidate movies. Rerank them by how well they match the user's "
    "INTENT (tone, pacing, narrative structure, mood — not just topic). Be strict "
    "about the non-obvious parts of the query. Return strict JSON: "
    '{"picks": [{"i": <candidate_index>, "why": "<one sentence>"}]} with exactly '
    f"{FINAL_N} picks, best first. Use the candidate index, do not invent titles."
)


def expand_query(query: str) -> str:
    r = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": EXPAND_SYSTEM},
            {"role": "user", "content": query},
        ],
        max_tokens=400,
        temperature=0.7,
    )
    return r.choices[0].message.content or ""


def embed(text_str: str) -> list[float]:
    r = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text_str,
    )
    return r.data[0].embedding


def pgvector_candidates(emb: list[float], db) -> list[tuple[int, float]]:
    emb_str = "[" + ",".join(str(v) for v in emb) + "]"
    rows = db.execute(
        text("SELECT * FROM match_movies(cast(:q AS vector(1536)), :n, :ex)"),
        {"q": emb_str, "n": POOL_SIZE, "ex": []},
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


EXCLUDED_GENRES = {"music", "documentary"}


def has_excluded_genre(movie: Movie) -> bool:
    for g in movie.genres or []:
        name = g.get("name", "").lower() if isinstance(g, dict) else ""
        if name in EXCLUDED_GENRES:
            return True
    return False


def first_pass_rerank(candidates: list[dict]) -> list[dict]:
    for c in candidates:
        m: Movie = c["movie"]
        consensus = (m.vote_average or 0) / 10.0
        c["first_score"] = 0.85 * c["similarity"] + 0.15 * consensus
    candidates.sort(key=lambda c: c["first_score"], reverse=True)
    return candidates[:RERANK_POOL]


def build_rerank_payload(query: str, cands: list[dict]) -> str:
    lines = [f"USER QUERY: {query}", "", "CANDIDATES:"]
    for i, c in enumerate(cands):
        m: Movie = c["movie"]
        genres = ", ".join(g.get("name", "") for g in (m.genres or [])[:4])
        overview = (m.overview or "")[:280]
        lines.append(
            f"[{i}] {m.title} ({m.year}) — dir. {m.director or '?'} | "
            f"{genres} | vote {m.vote_average}"
        )
        lines.append(f"    {overview}")
    return "\n".join(lines)


def llm_rerank(query: str, cands: list[dict]) -> list[dict]:
    payload = build_rerank_payload(query, cands)
    r = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": RERANK_SYSTEM},
            {"role": "user", "content": payload},
        ],
        response_format={"type": "json_object"},
        max_tokens=900,
        temperature=0.3,
    )
    raw = r.choices[0].message.content or "{}"
    picks = json.loads(raw).get("picks", [])
    out = []
    for p in picks:
        idx = p.get("i")
        if not isinstance(idx, int) or idx < 0 or idx >= len(cands):
            continue
        c = cands[idx]
        c["why"] = p.get("why", "")
        out.append(c)
    return out


def run_query(query: str, db) -> None:
    print("\n" + "=" * 80)
    print(f"QUERY: {query}")
    print("=" * 80)

    t0 = time.time()
    expanded = expand_query(query)
    t1 = time.time()
    print(f"\n[expand {t1 - t0:.2f}s] Ideal overview:")
    print(expanded[:400] + ("..." if len(expanded) > 400 else ""))

    t2 = time.time()
    emb = embed(expanded)
    t3 = time.time()
    print(f"\n[embed {t3 - t2:.2f}s]")

    t4 = time.time()
    rows = pgvector_candidates(emb, db)
    t5 = time.time()
    print(f"[pgvector {t5 - t4:.2f}s] {len(rows)} raw hits")

    tmdb_ids = [r[0] for r in rows]
    sim_map = dict(rows)
    movies = db.query(Movie).filter(Movie.tmdb_id.in_(tmdb_ids)).all()
    mmap = {m.tmdb_id: m for m in movies}

    cands = []
    for tid in tmdb_ids:
        m = mmap.get(tid)
        if not m:
            continue
        if (m.runtime or 0) < 45:
            continue
        if (m.vote_average or 0) < 5.5:
            continue
        if has_excluded_genre(m):
            continue
        cands.append({"tmdb_id": tid, "similarity": sim_map[tid], "movie": m})

    print(f"[filter] {len(cands)} after runtime/vote/genre filters")

    top30 = first_pass_rerank(cands)
    print(f"[first-pass] top {len(top30)} passed to LLM rerank")

    t6 = time.time()
    final = llm_rerank(query, top30)
    t7 = time.time()
    print(f"[llm rerank {t7 - t6:.2f}s] {len(final)} final picks")

    print(f"\nTOTAL LATENCY: {t7 - t0:.2f}s\n")
    print("RESULTS:")
    for rank, c in enumerate(final, 1):
        m = c["movie"]
        print(
            f"  {rank:2}. {m.title} ({m.year}) "
            f"[cos={c['similarity']:.3f} vote={m.vote_average}]"
        )
        print(f"      why: {c.get('why', '')}")


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
