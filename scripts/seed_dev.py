"""Seed the DEV environment: ~400 TMDB movies + embeddings, demo users, friendships, ratings.

Runs wherever the dev service's env vars are set (e.g. a Render one-off job or
`render ssh`), so no keys are handled by hand:

    uv run python scripts/seed_dev.py

Safe to re-run. Refuses to run against anything but the dev Supabase project.
"""

import asyncio
import logging
import random
import sys
from datetime import date

import httpx
from sqlalchemy import text

from app.auth.models import Profile
from app.config import settings
from app.database import SessionLocal
from app.dependencies import openai_client, supabase_admin
from app.friends.models import Friendship
from app.import_data.services import embed_movies, fetch_and_cache_movies
from app.recommendations.services import rebuild_taste_profile
from app.tracking.models import WatchedMovie, Watchlist

DEV_PROJECT_REF = "ikdbhiozrtetognqcxbp"
PROD_PROJECT_REF = "wtnbecnjsougjjcplhqf"
DEMO_PASSWORD = "Demo1234!"

logging.basicConfig(level=logging.INFO)

# username -> {tmdb_id: rating}
DEMOS = {
    "demo_casey": {
        27205: 5,
        157336: 4.5,
        155: 5,
        680: 4.5,
        550: 4,
        13: 4,
        603: 4.5,
        496243: 5,
        120467: 4,
        238: 4.5,
        872585: 4,
        693134: 4.5,
        545611: 4,
        419430: 3.5,
        324857: 4.5,
    },
    "demo_alex": {
        19404: 4,
        496243: 4.5,
        129: 5,
        372058: 5,
        299534: 4,
        24428: 3.5,
        671: 4,
        862: 4.5,
        508442: 4.5,
        150540: 4,
        354912: 4,
    },
    "demo_sam": {
        238: 5,
        240: 5,
        424: 4.5,
        389: 4.5,
        769: 4,
        278: 5,
        497: 4,
        122: 4,
        680: 5,
        807: 4.5,
    },
    "demo_maya": {120467: 5, 129: 4.5, 862: 5, 508442: 4, 354912: 4.5, 150540: 5},
}


def guard() -> None:
    url = settings.supabase_url
    if PROD_PROJECT_REF in url or DEV_PROJECT_REF not in url:
        sys.exit(f"Refusing to seed: SUPABASE_URL is not the dev project ({url!r})")
    if not (settings.tmdb_api_key and settings.openai_api_key):
        sys.exit("TMDB_API_KEY and OPENAI_API_KEY must be set")
    if supabase_admin is None:
        sys.exit("SUPABASE_SERVICE_KEY must be set (needed to create demo users)")


def ensure_user(db, username: str) -> Profile:
    prof = db.query(Profile).filter(Profile.username == username).first()
    if prof:
        return prof
    email = f"{username}@blnd.dev"
    created = supabase_admin.auth.admin.create_user(
        {"email": email, "password": DEMO_PASSWORD, "email_confirm": True}
    )
    wl = Watchlist()
    db.add(wl)
    db.flush()
    prof = Profile(
        id=created.user.id,
        username=username,
        display_name=username.removeprefix("demo_").title(),
        watchlist_id=wl.id,
        favorite_genres=["Science Fiction", "Thriller", "Drama"],
        subscription_tier="premium",
        subscription_source="admin",
        is_test=True,
    )
    db.add(prof)
    db.commit()
    print("created", username, email)
    return prof


async def main() -> None:
    guard()
    tmdb = httpx.AsyncClient(
        base_url="https://api.themoviedb.org/3",
        headers={"Authorization": f"Bearer {settings.tmdb_api_key}"},
        timeout=30,
    )
    ids: list[int] = []
    for path in [
        "/movie/popular",
        "/movie/top_rated",
        "/trending/movie/week",
        "/movie/now_playing",
    ]:
        for page in range(1, 9):
            r = await tmdb.get(path, params={"page": page})
            if r.status_code == 200:
                ids += [m["id"] for m in r.json().get("results", [])]
    ids += [t for ratings in DEMOS.values() for t in ratings]
    ids = list(dict.fromkeys(ids))
    print("candidate ids", len(ids))

    db = SessionLocal()
    print(await fetch_and_cache_movies(ids, db, tmdb))
    print(await embed_movies(db, openai_client))
    await tmdb.aclose()

    profiles = {u: ensure_user(db, u) for u in DEMOS}

    # Everyone is friends with everyone (accepted).
    plist = list(profiles.values())
    for i, a in enumerate(plist):
        for b in plist[i + 1 :]:
            exists = db.execute(
                text(
                    "select 1 from friendships where "
                    "(requester_id=:a and addressee_id=:b) or (requester_id=:b and addressee_id=:a)"
                ),
                {"a": str(a.id), "b": str(b.id)},
            ).first()
            if not exists:
                db.add(
                    Friendship(requester_id=a.id, addressee_id=b.id, status="accepted")
                )
    db.commit()

    cached = {r[0] for r in db.execute(text("select tmdb_id from movies")).all()}
    rng = random.Random(7)
    for uname, ratings in DEMOS.items():
        prof = profiles[uname]
        for tid, rating in ratings.items():
            if tid not in cached:
                continue
            if (
                not db.query(WatchedMovie)
                .filter_by(user_id=prof.id, tmdb_id=tid)
                .first()
            ):
                db.add(
                    WatchedMovie(
                        user_id=prof.id,
                        tmdb_id=tid,
                        rating=rating,
                        watched_date=date(2026, rng.randint(1, 9), rng.randint(1, 28)),
                        source="manual",
                    )
                )
        db.commit()
        rebuild_taste_profile(str(prof.id), db, openai_client)
        db.commit()
        print("rebuilt taste profile", uname)

    print("movies:", db.execute(text("select count(*) from movies")).scalar())
    print(f"done. demo logins: <username>@blnd.dev / {DEMO_PASSWORD}")


asyncio.run(main())
