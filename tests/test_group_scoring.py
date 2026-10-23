"""Per-member group scoring for Blend feeds (least-misery blended with the mean)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.groups.models import GroupMember
from app.groups.services import get_group_recommendations
from app.import_data.models import MovieEmbedding
from app.recommendations import pipeline
from app.recommendations.collaborative import (
    MIN_PROFILE_RATINGS,
    compute_cf_scores,
    compute_member_cf_scores,
)
from app.recommendations.group_reasons import attach_group_reasons
from app.recommendations.group_scoring import (
    MemberTaste,
    combine_member_scores,
    group_scores,
    rerank_group_candidates,
)
from app.recommendations.models import HiddenMovie, MovieInteraction
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.factories import make_group, make_movie, make_profile, make_watched


def _vec(*head: float) -> list[float]:
    """A 1536-d embedding whose first dimensions are `head`."""
    return list(head) + [0.0] * (1536 - len(head))


def _movie_obj(tmdb_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        tmdb_id=tmdb_id,
        genres=[],
        vote_average=7.0,
        director=None,
        cast=[],
    )


def _candidate(tmdb_id: int, similarity: float = 0.5) -> dict:
    return {
        "tmdb_id": tmdb_id,
        "similarity": similarity,
        "movie": _movie_obj(tmdb_id),
    }


# --- combining member scores ---


def test_default_weight_is_mostly_least_misery() -> None:
    assert Settings().group_least_misery_weight == pytest.approx(0.7)


def test_combine_is_weighted_min_plus_mean() -> None:
    # min=0.2, mean=0.5
    assert combine_member_scores([0.2, 0.8], 0.7) == pytest.approx(
        0.7 * 0.2 + 0.3 * 0.5
    )
    assert combine_member_scores([0.2, 0.8], 1.0) == pytest.approx(0.2)
    assert combine_member_scores([0.2, 0.8], 0.0) == pytest.approx(0.5)


def test_combine_clamps_weight_and_handles_one_score() -> None:
    assert combine_member_scores([0.2, 0.8], 5.0) == pytest.approx(0.2)
    assert combine_member_scores([0.2, 0.8], -1.0) == pytest.approx(0.5)
    assert combine_member_scores([0.6], 0.7) == pytest.approx(0.6)


# --- group_scores over per-member score tables ---

POLARIZING = 1  # one member loves it, the other is lukewarm-to-cold
CONSENSUS = 2  # both like it fine
FILLER = [3, 4, 5, 6]


def _disagreeing_pair() -> dict[str, dict[int, float]]:
    return {
        "a": {POLARIZING: 0.95, CONSENSUS: 0.65, 3: 0.40, 4: 0.35, 5: 0.30, 6: 0.30},
        "b": {POLARIZING: 0.35, CONSENSUS: 0.65, 3: 0.40, 4: 0.35, 5: 0.30, 6: 0.30},
    }


def test_disagreeing_pair_prefers_consensus_over_polarizing() -> None:
    tables = _disagreeing_pair()
    old_average = {t: (tables["a"][t] + tables["b"][t]) / 2 for t in tables["a"]}
    # The averaged score is what hid the disagreement: polarizing ties consensus.
    assert old_average[POLARIZING] == pytest.approx(old_average[CONSENSUS])

    scores = group_scores(tables, 0.7)
    assert scores[CONSENSUS] > scores[POLARIZING]
    assert scores[CONSENSUS] == max(scores.values())


def test_agreement_beats_one_sided_even_when_means_are_equal() -> None:
    tables = {
        "a": {1: 0.9, 2: 0.6, 3: 0.2, 4: 0.5},
        "b": {1: 0.3, 2: 0.6, 3: 0.2, 4: 0.5},
    }
    scores = group_scores(tables, 0.7)
    assert scores[2] > scores[1]


def test_members_have_equal_weight_regardless_of_score_scale() -> None:
    """A member whose raw scores span a wide range must not outvote a narrow one."""
    base = {
        "a": {1: 0.9, 2: 0.2, 3: 0.55, 4: 0.5, 5: 0.45},
        "b": {1: 0.40, 2: 0.60, 3: 0.52, 4: 0.50, 5: 0.48},
    }
    stretched = {
        "a": {t: 3.0 * s + 0.2 for t, s in base["a"].items()},
        "b": base["b"],
    }
    order = lambda table: sorted(table, key=lambda t: table[t], reverse=True)  # noqa: E731
    assert order(group_scores(base, 0.7)) == order(group_scores(stretched, 0.7))


def test_rating_count_does_not_change_weight() -> None:
    """Swapping which member is which leaves every group score unchanged."""
    tables = _disagreeing_pair()
    swapped = {"a": tables["b"], "b": tables["a"]}
    original = group_scores(tables, 0.7)
    flipped = group_scores(swapped, 0.7)
    assert original == pytest.approx(flipped)


def test_group_scores_degenerate_inputs() -> None:
    assert group_scores({}, 0.7) == {}
    flat = group_scores({"a": {1: 0.5}, "b": {1: 0.7}}, 0.7)
    assert flat[1] == pytest.approx(0.6)


# --- rerank_group_candidates ---


def _member(user_id: str, *head: float, **kwargs) -> MemberTaste:
    return MemberTaste(user_id=user_id, embedding=_vec(*head), **kwargs)


def test_rerank_prefers_candidate_both_members_like() -> None:
    a = _member("a", 1.0, 0.0)
    b = _member("b", 0.0, 1.0)
    candidates = [_candidate(1), _candidate(2), _candidate(3)]
    embeddings = {
        1: _vec(1.0, 0.0),  # only A
        2: _vec(0.0, 1.0),  # only B
        3: _vec(0.7, 0.7),  # both
    }
    ranked = rerank_group_candidates(candidates, [a, b], embeddings, {}, 0.7)
    assert ranked[0]["tmdb_id"] == 3
    assert {c["tmdb_id"] for c in ranked} == {1, 2, 3}
    assert all("score" in c for c in ranked)


def test_rerank_new_pair_without_cf_uses_each_members_embedding() -> None:
    a = _member("a", 1.0, 0.0)
    b = _member("b", 0.0, 1.0)
    candidates = [_candidate(1), _candidate(3), _candidate(4)]
    embeddings = {1: _vec(1.0, 0.0), 3: _vec(0.7, 0.7), 4: _vec(-0.7, -0.7)}
    ranked = rerank_group_candidates(candidates, [a, b], embeddings, {}, 0.7)
    assert ranked[0]["tmdb_id"] == 3


def test_rerank_heavy_cf_rater_does_not_drown_light_member() -> None:
    """Heavy rater has CF scores, light rater only an embedding; both count equally."""
    heavy = _member("heavy", 1.0, 0.0)
    light = _member("light", 0.0, 1.0)
    candidates = [_candidate(1), _candidate(2), _candidate(3), _candidate(4)]
    embeddings = {
        1: _vec(1.0, 0.0),  # heavy's favourite, light is cold on it
        2: _vec(0.0, 1.0),  # light's favourite, heavy is cold on it
        3: _vec(0.7, 0.7),  # both
        4: _vec(-1.0, -1.0),
    }
    heavy_cf = {1: 0.95, 2: 0.10, 3: 0.80, 4: 0.05}
    ranked = rerank_group_candidates(
        candidates, [heavy, light], embeddings, {"heavy": heavy_cf}, 0.7
    )
    assert ranked[0]["tmdb_id"] == 3


def test_rerank_negative_embedding_penalises_only_that_member() -> None:
    a = _member("a", 1.0, 1.0)
    b = _member("b", 1.0, 1.0, negative_embedding=_vec(0.0, 1.0))
    candidates = [_candidate(1), _candidate(2)]
    embeddings = {1: _vec(1.0, 0.0), 2: _vec(0.0, 1.0)}
    ranked = rerank_group_candidates(candidates, [a, b], embeddings, {}, 0.7)
    assert ranked[0]["tmdb_id"] == 1


# --- per-member CF ---


def _movies(db: Session, ids: list[int]) -> None:
    for tmdb_id in ids:
        make_movie(db, tmdb_id=tmdb_id, title=f"Movie {tmdb_id}")


def _user(db: Session, name: str) -> str:
    return str(make_profile(db, username=name).id)


def _rate(db: Session, user_id: str, ratings: dict[int, float]) -> None:
    for tmdb_id, rating in ratings.items():
        make_watched(db, user_id=user_id, tmdb_id=tmdb_id, rating=rating)


def test_member_cf_scores_each_member_on_their_own_ratings(db: Session) -> None:
    """A loves 1-3 and hates 4-5; B is the opposite. Old averaging flattened both."""
    _movies(db, [1, 2, 3, 4, 5, 100, 101])
    a = _user(db, "a")
    b = _user(db, "b")
    _rate(db, a, {1: 5.0, 2: 5.0, 3: 5.0, 4: 1.0, 5: 1.0})
    _rate(db, b, {1: 1.0, 2: 1.0, 3: 1.0, 4: 5.0, 5: 5.0})
    for i in range(4):  # fans of the 1-3 camp rate candidate 100 high, 101 low
        fan = _user(db, f"fan{i}")
        _rate(db, fan, {1: 5.0, 2: 5.0, 3: 5.0, 4: 1.0, 5: 1.0, 100: 5.0, 101: 1.0})
    for i in range(4):  # fans of the 4-5 camp do the reverse
        fan = _user(db, f"other{i}")
        _rate(db, fan, {1: 1.0, 2: 1.0, 3: 1.0, 4: 5.0, 5: 5.0, 100: 1.0, 101: 5.0})

    per_member = compute_member_cf_scores([a, b], [100, 101], db)

    assert set(per_member) == {a, b}
    assert per_member[a][100] > per_member[a][101]
    assert per_member[b][101] > per_member[b][100]
    # The old merged profile averages 5 and 1 to 3 everywhere: no direction at all.
    merged = compute_cf_scores([a, b], [100, 101], db)
    assert abs(merged[100] - merged[101]) < abs(per_member[a][100] - per_member[a][101])


def test_member_cf_light_rater_gets_no_cf_so_caller_falls_back(db: Session) -> None:
    _movies(db, [1, 2, 3, 4, 5, 100, 101, 102])
    heavy = _user(db, "heavy")
    light = _user(db, "light")
    _rate(db, heavy, {1: 5.0, 2: 5.0, 3: 5.0, 4: 1.0, 5: 1.0})
    _rate(db, light, {1: 5.0, 102: 4.0})
    assert 2 < MIN_PROFILE_RATINGS
    for i in range(4):
        fan = _user(db, f"fan{i}")
        _rate(db, fan, {1: 5.0, 2: 5.0, 3: 5.0, 4: 1.0, 5: 1.0, 100: 5.0, 101: 1.0})

    per_member = compute_member_cf_scores([heavy, light], [100, 101], db)

    assert per_member[heavy]
    assert per_member[light] == {}


def test_member_cf_empty_inputs(db: Session) -> None:
    assert compute_member_cf_scores([], [1], db) == {}
    assert compute_member_cf_scores(["x"], [], db) == {"x": {}}


# --- pipeline + service integration ---

CONSENSUS_ID = 9001
A_ONLY_ID = 9002
B_ONLY_ID = 9003


def _catalog(db: Session) -> None:
    """Three candidates: only A's taste, only B's taste, and both."""
    for tmdb_id, vec in (
        (A_ONLY_ID, _vec(1.0, 0.0)),
        (B_ONLY_ID, _vec(0.0, 1.0)),
        (CONSENSUS_ID, _vec(0.7, 0.7)),
    ):
        make_movie(
            db,
            tmdb_id=tmdb_id,
            title=f"Movie {tmdb_id}",
            runtime=120,
            vote_count=500,
            director=f"Director {tmdb_id}",
            cast=[{"name": f"Actor {tmdb_id}"}],
        )
        db.add(MovieEmbedding(tmdb_id=tmdb_id, embedding=vec))
    db.commit()


def _blend(db: Session, a_taste: list[float], b_taste: list[float]):
    a = make_profile(db, user_id=TEST_USER_ID, username="alice")
    b = make_profile(db, user_id=TEST_USER_ID_2, username="bob")
    a.taste_embedding = a_taste
    b.taste_embedding = b_taste
    db.commit()
    group, _ = make_group(db, name="Blend", created_by=TEST_USER_ID)
    db.add(GroupMember(group_id=group.id, user_id=TEST_USER_ID_2))
    db.commit()
    return group


# limit=300 keeps these independent of extra catalog rows (e.g. left by `make eval`).
def test_new_pair_with_no_ratings_still_gets_group_scores(db: Session) -> None:
    _catalog(db)
    group = _blend(db, _vec(1.0, 0.0), _vec(0.0, 1.0))

    results = get_group_recommendations(group.id, TEST_USER_ID, db, limit=300)[
        "results"
    ]

    by_id = {r["tmdb_id"]: r for r in results}
    assert CONSENSUS_ID in by_id
    assert by_id[CONSENSUS_ID]["match_score"] > by_id[A_ONLY_ID]["match_score"]
    assert by_id[CONSENSUS_ID]["match_score"] > by_id[B_ONLY_ID]["match_score"]


def test_group_feed_hard_filters_watched_and_not_for_me_of_any_member(
    db: Session,
) -> None:
    _catalog(db)
    for tmdb_id, vec in (
        (9101, _vec(0.7, 0.7)),
        (9102, _vec(0.7, 0.7)),
        (9103, _vec(0.7, 0.7)),
        (9104, _vec(0.7, 0.7)),
    ):
        make_movie(
            db, tmdb_id=tmdb_id, title=f"Movie {tmdb_id}", runtime=120, vote_count=500
        )
        db.add(MovieEmbedding(tmdb_id=tmdb_id, embedding=vec))
    db.commit()
    group = _blend(db, _vec(1.0, 0.0), _vec(0.0, 1.0))
    make_watched(db, user_id=TEST_USER_ID, tmdb_id=9101, rating=4.0)
    db.add(
        MovieInteraction(
            user_id=TEST_USER_ID_2, tmdb_id=9102, interaction_type="not_for_me"
        )
    )
    db.add(HiddenMovie(user_id=TEST_USER_ID_2, tmdb_id=9103))
    db.commit()

    results = get_group_recommendations(group.id, TEST_USER_ID, db, limit=300)[
        "results"
    ]

    shown = {r["tmdb_id"] for r in results}
    assert not shown & {9101, 9102, 9103}
    assert 9104 in shown


def test_group_results_carry_a_reason_for_algorithm_picks(db: Session) -> None:
    _catalog(db)
    group = _blend(db, _vec(1.0, 0.0), _vec(0.0, 1.0))
    results = get_group_recommendations(group.id, TEST_USER_ID, db, limit=300)[
        "results"
    ]
    top = next(r for r in results if r["tmdb_id"] == CONSENSUS_ID)
    assert isinstance(top["reason"], str) and top["reason"]


def test_run_main_algorithm_uses_per_member_scoring(db: Session) -> None:
    _catalog(db)
    members = [
        MemberTaste(TEST_USER_ID, _vec(1.0, 0.0)),
        MemberTaste(TEST_USER_ID_2, _vec(0.0, 1.0)),
    ]
    ctx = pipeline.RecommendationContext(
        positive_embedding=_vec(0.5, 0.5),
        members=members,
    )
    ranked = pipeline._run_main_algorithm(ctx, db)
    assert ranked[0]["tmdb_id"] == CONSENSUS_ID


def test_personal_feed_path_is_unchanged_without_members(db: Session) -> None:
    _catalog(db)
    ctx = pipeline.RecommendationContext(positive_embedding=_vec(1.0, 0.0))
    ranked = pipeline._run_main_algorithm(ctx, db)
    assert ranked[0]["tmdb_id"] == A_ONLY_ID
    assert "reason" not in ranked[0]


def test_group_weight_setting_is_used_by_the_rerank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = _member("a", 1.0, 0.0)
    b = _member("b", 0.0, 1.0)
    embeddings = {1: _vec(1.0, 0.0), 3: _vec(0.7, 0.7), 4: _vec(-0.7, -0.7)}

    def score_of_one_sided(weight: float) -> float:
        monkeypatch.setattr(settings, "group_least_misery_weight", weight)
        candidates = [_candidate(1), _candidate(3), _candidate(4)]
        ranked = rerank_group_candidates(candidates, [a, b], embeddings, {})
        return next(c["score"] for c in ranked if c["tmdb_id"] == 1)

    # Candidate 1 is loved by A and ignored by B: more least-misery, lower score.
    assert score_of_one_sided(1.0) < score_of_one_sided(0.0)


def test_group_weight_default_is_mostly_least_misery() -> None:
    assert 0.5 < Settings().group_least_misery_weight < 1.0


# --- reasons ---


def _reason_for(
    db: Session, candidate_id: int, members: list[MemberTaste]
) -> str | None:
    movie = db.query(pipeline.Movie).filter_by(tmdb_id=candidate_id).one()
    candidate = {"tmdb_id": candidate_id, "movie": movie, "score": 0.5}
    attach_group_reasons([candidate], members, db)
    return candidate.get("reason")


def test_reason_names_a_movie_both_rated_highly(db: Session) -> None:
    for tmdb_id, vec in (
        (10, _vec(1.0, 0.0)),
        (11, _vec(0.0, 1.0)),
        (12, _vec(0.95, 0.05)),
    ):
        make_movie(
            db,
            tmdb_id=tmdb_id,
            title=f"Title {tmdb_id}",
            runtime=120,
            director=f"D{tmdb_id}",
        )
        db.add(MovieEmbedding(tmdb_id=tmdb_id, embedding=vec))
    db.commit()
    a = str(make_profile(db, username="a").id)
    b = str(make_profile(db, username="b").id)
    make_watched(db, user_id=a, tmdb_id=10, rating=5.0)
    make_watched(db, user_id=b, tmdb_id=10, rating=4.5)
    make_watched(db, user_id=a, tmdb_id=11, rating=5.0)
    members = [MemberTaste(a, _vec(1.0)), MemberTaste(b, _vec(1.0))]

    assert _reason_for(db, 12, members) == "You both rated Title 10 highly"


def test_reason_says_all_for_three_members(db: Session) -> None:
    make_movie(db, tmdb_id=10, title="Title 10", runtime=120, director="X")
    make_movie(db, tmdb_id=12, title="Title 12", runtime=120, director="Y")
    db.add(MovieEmbedding(tmdb_id=10, embedding=_vec(1.0, 0.0)))
    db.add(MovieEmbedding(tmdb_id=12, embedding=_vec(0.95, 0.05)))
    db.commit()
    ids = [str(make_profile(db, username=n).id) for n in ("a", "b", "c")]
    for uid in ids:
        make_watched(db, user_id=uid, tmdb_id=10, rating=5.0)
    members = [MemberTaste(uid, _vec(1.0)) for uid in ids]

    assert _reason_for(db, 12, members) == "You all rated Title 10 highly"


def test_reason_falls_back_to_shared_director_then_genre_then_generic(
    db: Session,
) -> None:
    make_movie(
        db,
        tmdb_id=20,
        title="Directed",
        runtime=120,
        director="Greta Gerwig",
        genres=[{"id": 1, "name": "Comedy"}],
    )
    make_movie(
        db,
        tmdb_id=21,
        title="Comedy",
        runtime=120,
        director="Nobody",
        genres=[{"id": 1, "name": "Comedy"}],
    )
    make_movie(
        db,
        tmdb_id=22,
        title="Plain",
        runtime=120,
        director="Other",
        genres=[{"id": 2, "name": "War"}],
    )
    a = str(make_profile(db, username="a").id)
    b = str(make_profile(db, username="b").id)
    members = [
        MemberTaste(a, _vec(1.0), genres=["Comedy"], directors={"greta gerwig"}),
        MemberTaste(b, _vec(1.0), genres=["comedy"], directors={"greta gerwig"}),
    ]

    assert _reason_for(db, 20, members) == "You both rated Greta Gerwig films highly"
    assert _reason_for(db, 21, members) == "Matches both your Comedy picks"
    assert _reason_for(db, 22, members) == "Matches both your tastes"


# --- API shape / deprecation ---


def test_recommendations_endpoint_exposes_optional_reason(
    client: TestClient, db: Session
) -> None:
    _catalog(db)
    group = _blend(db, _vec(1.0, 0.0), _vec(0.0, 1.0))
    body = client.get(f"/groups/{group.id}/recommendations?limit=20").json()
    assert body["results"]
    assert all("reason" in r for r in body["results"])
    feed = client.post(
        f"/groups/{group.id}/recommendations/feed", json={"limit": 20}
    ).json()
    assert all("reason" in r for r in feed["results"])


def test_pick_tonight_routes_stay_but_are_deprecated(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path, method in (
        ("/groups/{group_id}/pick-tonight", "get"),
        ("/groups/{group_id}/pick-tonight/veto", "post"),
    ):
        assert paths[path][method]["deprecated"] is True
