"""Per-member scoring for Blend (group) feeds.

Each candidate is scored once per member, from that member's own taste: their
CF prediction when they have enough ratings, otherwise their taste embedding
(which is the onboarding genre seed until they rate more). Member scores are
standardised over the candidate pool so a member whose raw scores span a wide
range (a heavy rater with CF) cannot outvote one with a narrow range, then
combined as mostly the least-happy member (least misery) plus the mean.
Every member counts once, whatever their rating count.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.config import settings
from app.recommendations.ranking import _shuffle_within_tiers, score_for_taste


@dataclass
class MemberTaste:
    user_id: str
    embedding: list[float]
    negative_embedding: list[float] | None = None
    genres: list[str] = field(default_factory=list)
    directors: set[str] = field(default_factory=set)
    cast: set[str] = field(default_factory=set)


def combine_member_scores(scores: list[float], min_weight: float) -> float:
    """`min_weight` of the lowest score plus the rest on the mean."""
    weight = min(max(min_weight, 0.0), 1.0)
    return weight * min(scores) + (1.0 - weight) * (sum(scores) / len(scores))


def group_scores(
    member_scores: dict[str, dict[int, float]], min_weight: float
) -> dict[int, float]:
    """Combine {member: {tmdb_id: raw score}} into one score per candidate.

    Raw scores are z-scored per member, combined, then mapped back onto the
    average member's mean and spread so scores stay on the familiar scale.
    """
    if not member_scores:
        return {}
    stats = {}
    for uid, table in member_scores.items():
        values = np.array(list(table.values()))
        stats[uid] = (float(values.mean()), float(values.std()))
    mean = sum(m for m, _ in stats.values()) / len(stats)
    spread = sum(s for _, s in stats.values()) / len(stats)

    candidate_ids = next(iter(member_scores.values()))
    result = {}
    for tmdb_id in candidate_ids:
        z_scores = []
        for uid, table in member_scores.items():
            member_mean, member_std = stats[uid]
            z_scores.append(
                (table[tmdb_id] - member_mean) / member_std if member_std > 0 else 0.0
            )
        result[tmdb_id] = mean + spread * combine_member_scores(z_scores, min_weight)
    return result


def _unit_rows(vectors: list[list[float]]) -> np.ndarray:
    matrix = np.array(vectors, dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)


def rerank_group_candidates(
    candidates: list[dict],
    members: list[MemberTaste],
    candidate_embeddings: dict[int, list[float]],
    cf_by_member: dict[str, dict[int, float]],
    min_weight: float | None = None,
) -> list[dict]:
    """Score every candidate per member, then combine into the group score.

    Each candidate dict needs "movie", "similarity" (the pool's group-embedding
    cosine, used when a candidate has no stored embedding) and "tmdb_id".
    Returns candidates sorted by group score descending, with "score" added.
    """
    if not candidates or not members:
        return candidates
    weight = settings.group_least_misery_weight if min_weight is None else min_weight

    with_embedding = [c for c in candidates if c["tmdb_id"] in candidate_embeddings]
    similarity: dict[str, dict[int, float]] = {m.user_id: {} for m in members}
    negative: dict[str, dict[int, float]] = {m.user_id: {} for m in members}
    if with_embedding:
        cand_matrix = _unit_rows(
            [candidate_embeddings[c["tmdb_id"]] for c in with_embedding]
        )
        for m in members:
            sims = cand_matrix @ _unit_rows([m.embedding])[0]
            similarity[m.user_id] = {
                c["tmdb_id"]: float(s) for c, s in zip(with_embedding, sims)
            }
            if m.negative_embedding:
                neg = cand_matrix @ _unit_rows([m.negative_embedding])[0]
                negative[m.user_id] = {
                    c["tmdb_id"]: float(s) for c, s in zip(with_embedding, neg)
                }

    raw: dict[str, dict[int, float]] = {}
    for m in members:
        raw[m.user_id] = {
            c["tmdb_id"]: score_for_taste(
                c["movie"],
                similarity[m.user_id].get(c["tmdb_id"], float(c["similarity"])),
                cf_by_member.get(m.user_id, {}).get(c["tmdb_id"]),
                m.genres,
                m.directors,
                m.cast,
                negative[m.user_id].get(c["tmdb_id"]),
            )
            for c in candidates
        }

    combined = group_scores(raw, weight)
    for c in candidates:
        c["score"] = round(max(combined[c["tmdb_id"]], 0.0), 4)
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return _shuffle_within_tiers(candidates)
