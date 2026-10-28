"""Offline eval of embedding ranking vs the collaborative-filtering blend.

Run with `make eval`. It talks only to the local Supabase Postgres.
It deletes and reinserts movies 900001-900240 and users whose email ends in
`@eval.local`. Other local movies and the simulator accounts stay.

How the synthetic dataset is generated
--------------------------------------
Seed ``20261015`` (numpy Generator). The catalog is 240 movies, ids
900001-900240, across six genres. Each movie has an 8-number taste vector.
Its stored embedding is 1536 numbers: that taste vector, a small genre
marker, and tiny noise, then normalized. Cosine search can therefore see
genre and taste, and nothing else.

Four clusters of users each prefer one genre. A rating is the dot product of
the user and movie taste vectors, plus a little noise, snapped to half stars
from 0.5 to 5. The first 40 movies are a popularity head: they are four times
more likely to be watched.

Eight movies (two per cluster) are the part embeddings cannot see. The people
in that cluster rate them 5. Neighbours outside the cluster rate them 2. The
genre label still matches that cluster, so the genre term in the ranker does
not hide them. The stored embedding points at the opposite taste, the way a
bad synopsis vector would, so cosine search ranks them as a poor match.
Item-item CF can still find them, because cluster-mates who kept the movie in
their training history rated it 5.

Watches are ordered in time. ``watched_date`` starts at 2023-01-01 and steps
three days. Taste does not drift, so the holdout is "what they watched last",
not a change in taste. For each user the last watches are removed from the
database and used as ground truth:

- 12 users per cluster with 40 watches. The last 8 are held out (32 train, the
  5+ bucket). For 6 of the 12, one hidden cluster movie is in the holdout and
  the other is in training. For the other 6, both stay in training, so the
  holdout users still have neighbours who rated that movie.
- 4 users per cluster in the 1-4 bucket, with 1, 2, 3, or 4 training ratings
  and 2 held-out ratings.
- 3 users per cluster in the 0 bucket: 6 held-out ratings and nothing in the
  database. Their taste embedding is the genre-seed fallback.

Relevant holdout items are ratings of 4 or higher. NDCG uses that rating as
the grade (0 below 4) with the usual log discount. Both arms rank the same
``match_movies`` pool with ``rerank_candidates``. The CF arm is
``CF_ENABLED=true`` and ``CF_BLEND_WEIGHT=1`` (CF when it has support, else
the embedding). The other arm is ``CF_ENABLED=false``. Metrics use score
order, with tmdb id as the tie break, so the random within-tier shuffle does
not move the numbers. The catalog is smaller than the 500-movie pool, so this
run does not measure movies the embedding search would have dropped.
"""

from __future__ import annotations

import math
import os
import sys
import time
import uuid
from pathlib import Path
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

SEED = 20261015
N_MOVIES = 240
TMDB_BASE = 900_001
EMBED_DIM = 1536
LATENT = 8
N_CLUSTERS = 4
HEAD_MOVIES = 40
RELEVANT_AT = 4.0
HOLDOUT_KS = (10, 20)
LOCAL_DB = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

GENRES: tuple[tuple[str, int], ...] = (
    ("Action", 28),
    ("Comedy", 35),
    ("Drama", 18),
    ("Horror", 27),
    ("Science Fiction", 878),
    ("Romance", 10749),
)


def precision_at_k(recommended: list[int], relevant: set[int], k: int) -> float:
    """Share of the top k that the user actually liked."""
    if k <= 0:
        return 0.0
    hits = sum(1 for item in recommended[:k] if item in relevant)
    return hits / k


def recall_at_k(recommended: list[int], relevant: set[int], k: int) -> float:
    """Share of the user's liked holdout items that appear in the top k."""
    if not relevant:
        return 0.0
    hits = sum(1 for item in recommended[:k] if item in relevant)
    return hits / len(relevant)


def _dcg(grades: list[float]) -> float:
    return sum((2**grade - 1) / math.log2(i + 2) for i, grade in enumerate(grades))


def ndcg_at_k(recommended: list[int], grades: dict[int, float], k: int) -> float:
    """Normalized discounted cumulative gain. Grade 0 means not relevant."""
    shown = [grades.get(item, 0.0) for item in recommended[:k]]
    ideal = sorted(grades.values(), reverse=True)[:k]
    ideal += [0.0] * (k - len(ideal))
    ideal_dcg = _dcg(ideal[:k])
    if ideal_dcg == 0:
        return 0.0
    return _dcg(shown) / ideal_dcg


def _self_check() -> None:
    assert precision_at_k([1, 2, 3], {2, 3}, 2) == 0.5
    assert recall_at_k([1, 2], {2, 3}, 2) == 0.5
    grades = {1: 5.0, 2: 4.0}
    assert abs(ndcg_at_k([1, 2], grades, 2) - 1.0) < 1e-9
    assert ndcg_at_k([2, 1], grades, 2) < 1.0


def _half_star(value: float) -> float:
    stepped = round(value * 2) / 2
    return float(min(5.0, max(0.5, stepped)))


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        return vector
    return vector / norm


def _embedding(
    rng: np.random.Generator, latent: np.ndarray, genre_index: int
) -> list[float]:
    """Pack the taste vector so cosine follows it, with a small genre marker."""
    vector = np.zeros(EMBED_DIM)
    vector[:LATENT] = latent * 4.0
    vector[LATENT + genre_index] = 0.4
    vector[LATENT + len(GENRES) :] = rng.normal(
        0, 0.01, EMBED_DIM - LATENT - len(GENRES)
    )
    return _unit(vector).tolist()


def _build_catalog(rng: np.random.Generator) -> list[dict[str, Any]]:
    centers = rng.normal(size=(len(GENRES), LATENT))
    centers = np.stack([_unit(row) for row in centers])
    movies: list[dict[str, Any]] = []
    for index in range(N_MOVIES):
        genre_index = index % len(GENRES)
        name, genre_id = GENRES[genre_index]
        club = index % N_CLUSTERS if index < N_CLUSTERS * 2 else None
        if club is None:
            latent = _unit(centers[genre_index] + rng.normal(0, 0.18, LATENT))
            true_latent = latent
            stored = latent
            embed_genre = genre_index
        else:
            # The genre label matches the cluster that loves the movie. The
            # embedding points at the opposite taste, like a bad synopsis vector.
            cluster = club
            name, genre_id = GENRES[cluster]
            genre_index = cluster
            true_latent = _unit(centers[cluster] + rng.normal(0, 0.05, LATENT))
            opposite = (cluster + len(GENRES) // 2) % len(GENRES)
            stored = _unit(centers[opposite] + rng.normal(0, 0.05, LATENT))
            embed_genre = opposite
        secondary = None
        if club is None and rng.random() < 0.25:
            secondary = GENRES[(genre_index + 1) % len(GENRES)]
        genres = [{"id": genre_id, "name": name}]
        if secondary:
            genres.append({"id": secondary[1], "name": secondary[0]})
        movies.append(
            {
                "tmdb_id": TMDB_BASE + index,
                "index": index,
                "title": f"Eval Movie {index + 1}",
                "genres": genres,
                "genre_name": name,
                "true_latent": true_latent,
                "embedding": _embedding(rng, stored, embed_genre),
                "club": club,
                "vote_average": 7.0 + (index % 8) * 0.2,
            }
        )
    return movies


def _rate(
    rng: np.random.Generator, pref: np.ndarray, cluster: int, movie: dict[str, Any]
) -> float:
    if movie["club"] is not None:
        return 5.0 if movie["club"] == cluster else 2.0
    base = 3.0 + 2.4 * float(np.dot(pref, movie["true_latent"]))
    return _half_star(base + float(rng.normal(0, 0.2)))


def _weighted_sample(
    rng: np.random.Generator,
    movies: list[dict[str, Any]],
    pref: np.ndarray,
    count: int,
) -> list[dict[str, Any]]:
    weights = []
    for movie in movies:
        pop = 4.0 if movie["index"] < HEAD_MOVIES else 1.0
        affinity = math.exp(2.0 * float(np.dot(pref, movie["true_latent"])))
        weights.append(pop * affinity)
    probs = np.array(weights, dtype=np.float64)
    probs /= probs.sum()
    picked = rng.choice(len(movies), size=count, replace=False, p=probs)
    return [movies[int(i)] for i in picked]


def _stamp(
    order: list[dict[str, Any]],
    pref: np.ndarray,
    cluster: int,
    rng: np.random.Generator,
):
    start = date(2023, 1, 1)
    rows = []
    for offset, movie in enumerate(order):
        rows.append(
            (
                movie["tmdb_id"],
                _rate(rng, pref, cluster, movie),
                start + timedelta(days=3 * offset),
            )
        )
    return rows


def _new_user(
    rng: np.random.Generator,
    cluster: int,
    username: str,
    bucket: str,
    train: list[tuple[int, float, date]],
    test: list[tuple[int, float, date]],
    pref: np.ndarray,
) -> dict[str, Any]:
    genre_name = GENRES[cluster][0]
    return {
        "id": str(uuid.UUID(bytes=rng.bytes(16))),
        "username": username,
        "cluster": cluster,
        "bucket": bucket,
        "favorite_genres": [genre_name],
        "train": train,
        "test": test,
        "pref": pref,
    }


def _build_users(
    rng: np.random.Generator, movies: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    centers = []
    for cluster in range(N_CLUSTERS):
        owned = [m["true_latent"] for m in movies if m["club"] == cluster]
        centers.append(_unit(np.mean(owned, axis=0)))
    by_cluster: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for movie in movies:
        if movie["club"] is not None:
            by_cluster[movie["club"]].append(movie)
    plain = [movie for movie in movies if movie["club"] is None]
    users: list[dict[str, Any]] = []
    for cluster in range(N_CLUSTERS):
        train_club, test_club = by_cluster[cluster]
        pref = _unit(centers[cluster] + 0.2 * centers[(cluster + 1) % N_CLUSTERS])
        for slot in range(12):
            others = _weighted_sample(rng, plain, pref, 38)
            if slot < 6:
                order = [train_club, *others, test_club]
            else:
                order = [train_club, test_club, *others]
            stamped = _stamp(order, pref, cluster, rng)
            users.append(
                _new_user(
                    rng,
                    cluster,
                    f"eval_warm_{cluster}_{slot}",
                    "5+",
                    stamped[:-8],
                    stamped[-8:],
                    pref,
                )
            )
        for slot, train_n in enumerate((1, 2, 3, 4)):
            order = _weighted_sample(rng, plain, pref, train_n + 2)
            stamped = _stamp(order, pref, cluster, rng)
            users.append(
                _new_user(
                    rng,
                    cluster,
                    f"eval_light_{cluster}_{slot}",
                    "1-4",
                    stamped[:-2],
                    stamped[-2:],
                    pref,
                )
            )
        for slot in range(3):
            order = _weighted_sample(rng, plain, pref, 6)
            stamped = _stamp(order, pref, cluster, rng)
            users.append(
                _new_user(
                    rng, cluster, f"eval_cold_{cluster}_{slot}", "0", [], stamped, pref
                )
            )
    return users


def _reset_local(connection: Session) -> None:
    """Delete only this script's rows. The simulator catalog stays in place."""
    lo = TMDB_BASE
    hi = TMDB_BASE + N_MOVIES - 1
    connection.execute(
        text("DELETE FROM public.watched_movies WHERE tmdb_id BETWEEN :lo AND :hi"),
        {"lo": lo, "hi": hi},
    )
    connection.execute(
        text("DELETE FROM public.watchlist_movies WHERE tmdb_id BETWEEN :lo AND :hi"),
        {"lo": lo, "hi": hi},
    )
    connection.execute(
        text("DELETE FROM public.movies WHERE tmdb_id BETWEEN :lo AND :hi"),
        {"lo": lo, "hi": hi},
    )
    # groups.created_by does not cascade, so a group owned by an eval user
    # blocks deleting that user.
    connection.execute(
        text(
            "DELETE FROM public.groups WHERE created_by IN ("
            "SELECT p.id FROM public.profiles p "
            "JOIN auth.users u ON u.id = p.id "
            "WHERE u.email LIKE '%@eval.local')"
        )
    )
    connection.execute(text("DELETE FROM auth.users WHERE email LIKE '%@eval.local'"))
    connection.commit()


def _insert_auth(connection: Session, user_id: str, email: str) -> None:
    connection.execute(
        text(
            "INSERT INTO auth.users (id, instance_id, aud, role, email, created_at, updated_at) "
            "VALUES (:id, '00000000-0000-0000-0000-000000000000', 'authenticated', "
            "'authenticated', :email, now(), now())"
        ),
        {"id": user_id, "email": email},
    )


def _seed(db, movies: list[dict[str, Any]], users: list[dict[str, Any]]) -> None:
    from app.auth.models import Profile
    from app.import_data.models import MovieEmbedding
    from app.movies.models import Movie
    from app.recommendations.services import (
        compute_genre_seed_embedding,
        compute_taste_embeddings,
    )
    from app.tracking.models import WatchedMovie

    _reset_local(db)
    db.add_all(
        [
            Movie(
                tmdb_id=movie["tmdb_id"],
                title=movie["title"],
                year=2010 + (movie["index"] % 15),
                overview="Synthetic title for the offline recommender eval.",
                genres=movie["genres"],
                runtime=110,
                vote_average=movie["vote_average"],
                vote_count=200,
                director=f"Director {movie['index']}",
                cast=[{"name": f"Actor {movie['index']}"}],
            )
            for movie in movies
        ]
    )
    db.commit()
    db.add_all(
        [
            MovieEmbedding(tmdb_id=movie["tmdb_id"], embedding=movie["embedding"])
            for movie in movies
        ]
    )
    db.commit()

    for user in users:
        _insert_auth(db, user["id"], f"{user['username']}@eval.local")
        db.add(
            Profile(
                id=user["id"],
                username=user["username"],
                favorite_genres=user["favorite_genres"],
            )
        )
    db.commit()

    for user in users:
        for tmdb_id, rating, watched_on in user["train"]:
            db.add(
                WatchedMovie(
                    user_id=user["id"],
                    tmdb_id=tmdb_id,
                    rating=rating,
                    watched_date=watched_on,
                    source="eval",
                )
            )
    db.commit()

    for user in users:
        profile = db.query(Profile).filter(Profile.id == user["id"]).one()
        positive, negative, weights = compute_taste_embeddings(user["id"], db, profile)
        if positive is None:
            positive = compute_genre_seed_embedding(user["favorite_genres"], db)
            negative = None
            weights = None
        if positive is None:
            raise RuntimeError(f"no taste embedding for {user['username']}")
        profile.taste_embedding = positive
        profile.negative_embedding = negative
        profile.taste_sum_weights = weights
        user["taste"] = list(positive)
        user["negative"] = list(negative) if negative is not None else None
    db.commit()


def _candidate_pool(db, taste: list[float], seen: list[int]) -> list[dict[str, Any]]:
    """The pgvector pool the pipeline would draw, minus movies already watched."""
    from sqlalchemy import text

    from app.movies.models import Movie
    from app.recommendations.pipeline import CANDIDATE_POOL_SIZE

    embedding = "[" + ",".join(str(value) for value in taste) + "]"
    rows = db.execute(
        text(
            "SELECT me.tmdb_id, "
            "1 - (me.embedding <=> cast(:query_embedding AS vector(1536))::halfvec(1536)) "
            "AS similarity "
            "FROM movie_embeddings me "
            "WHERE me.tmdb_id BETWEEN :lo AND :hi "
            "AND me.tmdb_id != ALL(cast(:exclude_ids AS int[])) "
            "ORDER BY me.embedding <=> cast(:query_embedding AS vector(1536))::halfvec(1536) "
            "LIMIT :match_count"
        ),
        {
            "query_embedding": embedding,
            "match_count": CANDIDATE_POOL_SIZE,
            "exclude_ids": seen or [0],
            "lo": TMDB_BASE,
            "hi": TMDB_BASE + N_MOVIES - 1,
        },
    ).fetchall()
    tmdb_ids = [row[0] for row in rows]
    similarity = {row[0]: float(row[1]) for row in rows}
    movies = (
        db.query(Movie).filter(Movie.tmdb_id.in_(tmdb_ids)).all() if tmdb_ids else []
    )
    movie_map = {movie.tmdb_id: movie for movie in movies}
    candidates = []
    for tmdb_id in tmdb_ids:
        movie = movie_map.get(tmdb_id)
        if not movie:
            continue
        if (movie.runtime or 0) < 45 or (movie.vote_average or 0) < 1.0:
            continue
        candidates.append(
            {"tmdb_id": tmdb_id, "similarity": similarity[tmdb_id], "movie": movie}
        )
    return candidates


def _recommend(db, user: dict[str, Any], arm: str) -> tuple[list[int], float]:
    from app.config import settings
    from app.import_data.models import MovieEmbedding
    from app.recommendations.collaborative import compute_cf_scores
    from app.recommendations.ranking import rerank_candidates
    from app.recommendations.services import get_user_signal_context

    settings.cf_enabled = arm == "cf"
    settings.cf_blend_weight = 1.0
    started = time.perf_counter()
    genres, directors, cast = get_user_signal_context(user["id"], db)
    candidates = _candidate_pool(
        db, user["taste"], [tmdb_id for tmdb_id, _, _ in user["train"]]
    )
    tmdb_ids = [c["tmdb_id"] for c in candidates]
    candidate_embeddings = None
    if user["negative"] is not None and tmdb_ids:
        emb_rows = (
            db.query(MovieEmbedding).filter(MovieEmbedding.tmdb_id.in_(tmdb_ids)).all()
        )
        candidate_embeddings = {row.tmdb_id: list(row.embedding) for row in emb_rows}
    ranked = rerank_candidates(
        candidates,
        genres,
        directors,
        cast,
        negative_embedding=user["negative"],
        candidate_embeddings=candidate_embeddings,
        cf_scores=compute_cf_scores(
            [user["id"]], [c["tmdb_id"] for c in candidates], db
        ),
    )
    ranked.sort(key=lambda candidate: (-candidate["score"], candidate["tmdb_id"]))
    elapsed_ms = (time.perf_counter() - started) * 1000
    return [candidate["tmdb_id"] for candidate in ranked], elapsed_ms


def _true_rating(user: dict[str, Any], movie: dict[str, Any]) -> float:
    """What the user would rate the movie, with no noise."""
    if movie["club"] is not None:
        return 5.0 if movie["club"] == user["cluster"] else 2.0
    return min(
        5.0, max(0.5, 3.0 + 2.4 * float(np.dot(user["pref"], movie["true_latent"])))
    )


def _recommend_group(db, members: list[dict[str, Any]], arm: str) -> list[int]:
    """Top movies for a blend. arm "averaged" is the old path, "per-member" the new one."""
    from app.config import settings
    from app.import_data.models import MovieEmbedding
    from app.recommendations.collaborative import (
        compute_cf_scores,
        compute_member_cf_scores,
    )
    from app.recommendations.group_scoring import MemberTaste, rerank_group_candidates
    from app.recommendations.ranking import rerank_candidates
    from app.recommendations.services import get_user_signal_context

    settings.cf_enabled = True
    settings.cf_blend_weight = 1.0
    signals = {m["id"]: get_user_signal_context(m["id"], db) for m in members}
    negatives = [m["negative"] for m in members if m["negative"] is not None]
    group_taste = np.mean([m["taste"] for m in members], axis=0).tolist()
    group_negative = np.mean(negatives, axis=0).tolist() if negatives else None
    seen = [tmdb_id for m in members for tmdb_id, _, _ in m["train"]]
    candidates = _candidate_pool(db, group_taste, seen)
    tmdb_ids = [c["tmdb_id"] for c in candidates]
    emb_rows = (
        db.query(MovieEmbedding).filter(MovieEmbedding.tmdb_id.in_(tmdb_ids)).all()
    )
    embeddings = {row.tmdb_id: list(row.embedding) for row in emb_rows}

    if arm == "averaged":
        ranked = rerank_candidates(
            candidates,
            sorted({g for gs, _, _ in signals.values() for g in gs}),
            {d for _, ds, _ in signals.values() for d in ds},
            {c for _, _, cs in signals.values() for c in cs},
            negative_embedding=group_negative,
            candidate_embeddings=embeddings,
            cf_scores=compute_cf_scores([m["id"] for m in members], tmdb_ids, db),
        )
    else:
        ranked = rerank_group_candidates(
            candidates,
            [
                MemberTaste(
                    user_id=m["id"],
                    embedding=m["taste"],
                    negative_embedding=m["negative"],
                    genres=list(signals[m["id"]][0]),
                    directors=set(signals[m["id"]][1]),
                    cast=set(signals[m["id"]][2]),
                )
                for m in members
            ],
            embeddings,
            compute_member_cf_scores([m["id"] for m in members], tmdb_ids, db),
        )
    ranked.sort(key=lambda candidate: (-candidate["score"], candidate["tmdb_id"]))
    return [candidate["tmdb_id"] for candidate in ranked]


def _example_pairs(
    users: list[dict[str, Any]],
) -> dict[str, list[tuple[dict[str, Any], dict[str, Any]]]]:
    """Blends of every kind the old averaging handled badly, picked by name."""
    by_name = {u["username"]: u for u in users}
    clusters = range(N_CLUSTERS)
    pairs: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {
        "same taste, both 5+": [],
        "disagree, both 5+": [],
        "new pair, both 1-4": [],
        "heavy + light": [],
        "cold pair, both 0": [],
    }
    for a in clusters:
        for slot in (0, 2):
            pairs["same taste, both 5+"].append(
                (by_name[f"eval_warm_{a}_{slot}"], by_name[f"eval_warm_{a}_{slot + 1}"])
            )
        for b in clusters:
            if a == b:
                continue
            for slot in (0, 1):
                pairs["heavy + light"].append(
                    (
                        by_name[f"eval_warm_{a}_{slot}"],
                        by_name[f"eval_light_{b}_{slot + 1}"],
                    )
                )
            if a < b:
                for slot in (0, 1):
                    pairs["disagree, both 5+"].append(
                        (
                            by_name[f"eval_warm_{a}_{slot}"],
                            by_name[f"eval_warm_{b}_{slot}"],
                        )
                    )
                    pairs["new pair, both 1-4"].append(
                        (
                            by_name[f"eval_light_{a}_{slot}"],
                            by_name[f"eval_light_{b}_{slot + 2}"],
                        )
                    )
                pairs["cold pair, both 0"].append(
                    (by_name[f"eval_cold_{a}_0"], by_name[f"eval_cold_{b}_0"])
                )
    return pairs


GROUP_ARMS = ("averaged", "per-member")
GROUP_K = 10


def _evaluate_groups(
    db, users: list[dict[str, Any]], movies: list[dict[str, Any]]
) -> dict[str, dict[str, dict[str, float]]]:
    """Old averaged blend vs per-member least misery, scored on true ratings.

    For each pair the top 10 is judged by what each member would really rate
    the movies (no noise, nothing from their history). "both like" means both
    members would give 4 or more. "worst" is the lower of the two ratings,
    averaged over the list. "regret" is the share of the list that at least
    one member would rate under 3.
    """
    by_id = {m["tmdb_id"]: m for m in movies}
    result: dict[str, dict[str, dict[str, float]]] = {}
    for kind, pairs in _example_pairs(users).items():
        samples: dict[str, list[dict[str, float]]] = {arm: [] for arm in GROUP_ARMS}
        for a, b in pairs:
            for arm in GROUP_ARMS:
                top = _recommend_group(db, [a, b], arm)[:GROUP_K]
                mins = [
                    min(_true_rating(a, by_id[t]), _true_rating(b, by_id[t]))
                    for t in top
                ]
                samples[arm].append(
                    {
                        "both_like": float(np.mean([m >= RELEVANT_AT for m in mins])),
                        "worst": float(np.mean(mins)),
                        "regret": float(np.mean([m < 3.0 for m in mins])),
                    }
                )
        result[kind] = {
            arm: {
                "n": float(len(rows)),
                **{
                    key: float(np.mean([row[key] for row in rows]))
                    for key in ("both_like", "worst", "regret")
                },
            }
            for arm, rows in samples.items()
        }
    return result


def _print_group_report(groups: dict[str, dict[str, dict[str, float]]]) -> None:
    from app.config import settings

    print()
    print(
        f"Blend feeds: old averaged profile vs per-member scoring "
        f"(least-misery weight {settings.group_least_misery_weight}). "
        f"Top {GROUP_K}, judged on each member's true rating."
    )
    print()
    print("| pair type | arm | pairs | both like >=4 | worst rating | regret <3 |")
    print("| --- | --- | ---: | ---: | ---: | ---: |")
    for kind, arms in groups.items():
        for arm in GROUP_ARMS:
            row = arms[arm]
            print(
                f"| {kind} | {arm} | {row['n']:.0f} | {row['both_like']:.3f} "
                f"| {row['worst']:.2f} | {row['regret']:.3f} |"
            )


def _grades(user: dict[str, Any]) -> tuple[set[int], dict[int, float]]:
    relevant = {tmdb_id for tmdb_id, rating, _ in user["test"] if rating >= RELEVANT_AT}
    grades = {
        tmdb_id: rating for tmdb_id, rating, _ in user["test"] if rating >= RELEVANT_AT
    }
    return relevant, grades


def _popularity_percentile(counts: dict[int, int], tmdb_id: int) -> float:
    count = counts.get(tmdb_id, 0)
    below = sum(1 for other in counts.values() if other < count)
    return below / max(len(counts) - 1, 1)


def _summarize(rows: list[dict[str, Any]], catalog: int) -> dict[str, float]:
    """Macro-average the per-user metrics. Coverage is over the union of lists."""
    summary: dict[str, float] = {"n": float(len(rows))}
    for key in ("p10", "r10", "n10", "p20", "r20", "n20", "pop20"):
        summary[key] = float(np.mean([row[key] for row in rows])) if rows else 0.0
    recommended = {tmdb_id for row in rows for tmdb_id in row["top20"]}
    summary["cov20"] = len(recommended) / catalog if catalog else 0.0
    latencies = [row["ms"] for row in rows]
    summary["p50"] = float(np.percentile(latencies, 50)) if latencies else 0.0
    summary["p95"] = float(np.percentile(latencies, 95)) if latencies else 0.0
    return summary


def _evaluate(
    db, users: list[dict[str, Any]], movies: list[dict[str, Any]]
) -> dict[tuple[str, str], dict[str, float]]:
    db.execute(text("SET ivfflat.probes = 100"))
    # The ivfflat index was built for a much larger catalog (lists = 100).
    # A sequential scan is exact at this size.
    db.execute(text("SET enable_indexscan = off"))
    popularity: dict[int, int] = defaultdict(int)
    for user in users:
        for tmdb_id, _, _ in user["train"]:
            popularity[tmdb_id] += 1
    for movie in movies:
        popularity.setdefault(movie["tmdb_id"], 0)

    _recommend(db, users[0], "embeddings")
    per_arm: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    latencies: dict[tuple[str, str], list[float]] = defaultdict(list)
    identical_cold = 0
    cold_users = 0
    for user in users:
        relevant, grades = _grades(user)
        lists: dict[str, list[int]] = {}
        for arm in ("embeddings", "cf"):
            ranked, elapsed_ms = _recommend(db, user, arm)
            lists[arm] = ranked
            latencies[(user["bucket"], arm)].append(elapsed_ms)
            if not relevant:
                continue
            per_arm[(user["bucket"], arm)].append(
                {
                    "p10": precision_at_k(ranked, relevant, 10),
                    "r10": recall_at_k(ranked, relevant, 10),
                    "n10": ndcg_at_k(ranked, grades, 10),
                    "p20": precision_at_k(ranked, relevant, 20),
                    "r20": recall_at_k(ranked, relevant, 20),
                    "n20": ndcg_at_k(ranked, grades, 20),
                    "pop20": float(
                        np.mean(
                            [
                                _popularity_percentile(popularity, tmdb_id)
                                for tmdb_id in ranked[:20]
                            ]
                        )
                    )
                    if ranked
                    else 0.0,
                    "top20": ranked[:20],
                    "ms": elapsed_ms,
                }
            )
        if len(user["train"]) < 5:
            cold_users += 1
            if lists["embeddings"][:20] == lists["cf"][:20]:
                identical_cold += 1
    catalog = len(movies)
    summary = {key: _summarize(rows, catalog) for key, rows in per_arm.items()}
    for (bucket, arm), samples in latencies.items():
        if (bucket, arm) in summary and samples:
            summary[(bucket, arm)]["p50"] = float(np.percentile(samples, 50))
            summary[(bucket, arm)]["p95"] = float(np.percentile(samples, 95))
    for arm in ("embeddings", "cf"):
        combined = [
            row
            for (bucket, row_arm), rows in per_arm.items()
            if row_arm == arm
            for row in rows
        ]
        summary[("all", arm)] = _summarize(combined, catalog)
        all_ms = [
            ms
            for (bucket, row_arm), samples in latencies.items()
            if row_arm == arm
            for ms in samples
        ]
        if all_ms:
            summary[("all", arm)]["p50"] = float(np.percentile(all_ms, 50))
            summary[("all", arm)]["p95"] = float(np.percentile(all_ms, 95))
    summary[("cold-lists", "match")] = {
        "n": float(cold_users),
        "matched": float(identical_cold),
    }
    return summary


def _print_report(
    users: list[dict[str, Any]], summary: dict[tuple[str, str], dict[str, float]]
) -> None:
    buckets = {"0": 0, "1-4": 0, "5+": 0}
    train_ratings = 0
    test_ratings = 0
    for user in users:
        buckets[user["bucket"]] += 1
        train_ratings += len(user["train"])
        test_ratings += len(user["test"])
    print("Dataset: seed 20261015, 240 movies, four taste clusters.")
    print(
        f"Users: 0={buckets['0']}, 1-4={buckets['1-4']}, 5+={buckets['5+']}. "
        f"Train ratings in the DB: {train_ratings}. Held-out ratings: {test_ratings}."
    )
    print(
        "Arms: embeddings = CF_ENABLED=false. "
        "cf = CF_ENABLED=true, CF_BLEND_WEIGHT=1 (CF when it has support)."
    )
    print()
    header = (
        "| bucket | arm | n | P@10 | R@10 | NDCG@10 | P@20 | R@20 | NDCG@20 "
        "| cov@20 | pop@20 | p50 ms | p95 ms |"
    )
    print(header)
    print(
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    for bucket in ("0", "1-4", "5+", "all"):
        for arm in ("embeddings", "cf"):
            rows_summary = summary.get((bucket, arm))
            if not rows_summary:
                continue
            print(
                "| {bucket} | {arm} | {n:.0f} | {p10:.3f} | {r10:.3f} | {n10:.3f} "
                "| {p20:.3f} | {r20:.3f} | {n20:.3f} | {cov20:.3f} | {pop20:.3f} "
                "| {p50:.1f} | {p95:.1f} |".format(
                    bucket=bucket, arm=arm, **rows_summary
                )
            )
    cold = summary[("cold-lists", "match")]
    print()
    print(
        f"Cold-start lists (train ratings under 5): {cold['matched']:.0f} of "
        f"{cold['n']:.0f} users got the same top 20 from both arms."
    )


def main() -> None:
    _self_check()
    url = os.environ.get("EVAL_DATABASE_URL", LOCAL_DB)
    if "127.0.0.1" not in url and "localhost" not in url:
        raise SystemExit(f"refusing non-local database: {url}")
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
    os.environ.setdefault("SUPABASE_KEY", "local-eval")
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from app.config import settings

    rng = np.random.default_rng(SEED)
    movies = _build_catalog(rng)
    users = _build_users(rng, movies)
    engine = create_engine(url)
    db = Session(engine)
    try:
        _seed(db, movies, users)
        summary = _evaluate(db, users, movies)
        groups = _evaluate_groups(db, users, movies)
    finally:
        settings.cf_enabled = True
        settings.cf_blend_weight = 1.0
        db.close()
        engine.dispose()
    _print_report(users, summary)
    _print_group_report(groups)
    cold = summary[("cold-lists", "match")]
    if cold["matched"] != cold["n"]:
        raise SystemExit(
            "CF changed recommendations for users with fewer than 5 ratings"
        )


if __name__ == "__main__":
    main()
