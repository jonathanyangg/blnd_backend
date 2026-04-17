import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.rate_limit import LIMIT_DEFAULT, LIMIT_SEARCH, limiter
from app.dependencies import (
    get_current_user,
    get_db,
    get_optional_user,
    get_tmdb_client,
)
from app.movies import schemas, services

router = APIRouter()


def _parse_exclude(exclude: str) -> set[int] | None:
    """Parse comma-separated tmdb_id string into a set."""
    if not exclude:
        return None
    try:
        return {int(x) for x in exclude.split(",") if x.strip()}
    except ValueError:
        return None


@router.get("/trending", response_model=schemas.MovieSearchResult)
@limiter.limit(LIMIT_DEFAULT)
async def get_trending_movies(
    request: Request,
    background_tasks: BackgroundTasks,
    exclude: str = Query(default="", description="Comma-separated tmdb_ids to exclude"),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    exclude_ids = _parse_exclude(exclude)
    try:
        data = await services.get_trending_movies(tmdb_client, exclude=exclude_ids)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="TMDB API error")

    data["results"], uncached = services.enrich_from_cache(data["results"], db)
    if uncached:
        background_tasks.add_task(services.cache_movies_in_background, uncached)

    tmdb_ids = [r["tmdb_id"] for r in data["results"]]
    scores = services.compute_match_scores(tmdb_ids, user_id, db)
    for r in data["results"]:
        r["match_score"] = scores.get(r["tmdb_id"])

    return data


@router.get("/top-rated", response_model=schemas.MovieSearchResult)
@limiter.limit(LIMIT_DEFAULT)
async def get_top_rated_movies(
    request: Request,
    background_tasks: BackgroundTasks,
    exclude: str = Query(default="", description="Comma-separated tmdb_ids to exclude"),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    exclude_ids = _parse_exclude(exclude)
    try:
        data = await services.get_top_rated_movies(tmdb_client, exclude=exclude_ids)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="TMDB API error")

    data["results"], uncached = services.enrich_from_cache(data["results"], db)
    if uncached:
        background_tasks.add_task(services.cache_movies_in_background, uncached)

    tmdb_ids = [r["tmdb_id"] for r in data["results"]]
    scores = services.compute_match_scores(tmdb_ids, user_id, db)
    for r in data["results"]:
        r["match_score"] = scores.get(r["tmdb_id"])

    return data


@router.get("/search/person", response_model=schemas.PersonSearchResult)
@limiter.limit(LIMIT_SEARCH)
async def search_person(
    request: Request,
    query: str = Query(min_length=1),
    _user_id: str = Depends(get_current_user),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    try:
        return await services.search_people(query, 1, tmdb_client)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="TMDB API error")


@router.get("/person/{person_id}/credits", response_model=schemas.MovieSearchResult)
@limiter.limit(LIMIT_DEFAULT)
async def get_person_credits(
    request: Request,
    person_id: int,
    background_tasks: BackgroundTasks,
    exclude: str = Query(default="", description="Comma-separated tmdb_ids to exclude"),
    user_id: str | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    exclude_ids = _parse_exclude(exclude)
    try:
        data = await services.discover_movies_by_actor(
            person_id, tmdb_client, exclude=exclude_ids
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="TMDB API error")

    data["results"], uncached = services.enrich_from_cache(data["results"], db)
    if uncached:
        background_tasks.add_task(services.cache_movies_in_background, uncached)

    if user_id:
        tmdb_ids = [r["tmdb_id"] for r in data["results"]]
        scores = services.compute_match_scores(tmdb_ids, user_id, db)
        for r in data["results"]:
            r["match_score"] = scores.get(r["tmdb_id"])

    return data


@router.get("/discover", response_model=schemas.MovieSearchResult)
@limiter.limit(LIMIT_SEARCH)
async def discover_movies(
    request: Request,
    background_tasks: BackgroundTasks,
    genres: str = Query(default="", description="Comma-separated genre names"),
    with_cast: int | None = Query(default=None, description="TMDB person ID"),
    exclude: str = Query(default="", description="Comma-separated tmdb_ids to exclude"),
    user_id: str | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    genre_list = [g.strip() for g in genres.split(",") if g.strip()]
    exclude_ids = _parse_exclude(exclude)

    if not genre_list and with_cast is None:
        raise HTTPException(
            status_code=400, detail="Either genres or with_cast is required"
        )

    try:
        if with_cast is not None:
            data = await services.discover_movies_by_actor(
                with_cast,
                tmdb_client,
                exclude=exclude_ids,
                genre_names=genre_list or None,
            )
        else:
            data = await services.discover_movies_by_genres(
                genre_list, tmdb_client, exclude=exclude_ids
            )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="TMDB API error")

    data["results"], uncached = services.enrich_from_cache(data["results"], db)
    if uncached:
        background_tasks.add_task(services.cache_movies_in_background, uncached)

    if user_id:
        tmdb_ids = [r["tmdb_id"] for r in data["results"]]
        scores = services.compute_match_scores(tmdb_ids, user_id, db)
        for r in data["results"]:
            r["match_score"] = scores.get(r["tmdb_id"])

    return data


@router.get("/search", response_model=schemas.MovieSearchResult)
@limiter.limit(LIMIT_SEARCH)
async def search_movies(
    request: Request,
    query: str = Query(min_length=1),
    page: int = Query(default=1, ge=1, le=500),
    _user_id: str = Depends(get_current_user),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    try:
        return await services.search_movies(query, page, tmdb_client)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="TMDB API error")


@router.get("/{tmdb_id}", response_model=schemas.MovieResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_movie(
    request: Request,
    tmdb_id: int,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    try:
        movie = await services.get_movie_details(tmdb_id, db, tmdb_client)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Movie not found")
        raise HTTPException(status_code=e.response.status_code, detail="TMDB API error")

    scores = services.compute_match_scores([tmdb_id], user_id, db)

    # Backfill missing embedding asynchronously so next view gets a real score
    from app.import_data.models import MovieEmbedding

    has_embedding = (
        db.query(MovieEmbedding.tmdb_id)
        .filter(MovieEmbedding.tmdb_id == tmdb_id)
        .first()
        is not None
    )
    if not has_embedding:
        background_tasks.add_task(services.embed_movie_in_background, tmdb_id)

    return schemas.MovieResponse(
        tmdb_id=movie.tmdb_id,
        title=movie.title,
        year=movie.year,
        overview=movie.overview,
        poster_path=movie.poster_path,
        genres=movie.genres or [],
        runtime=movie.runtime,
        vote_average=movie.vote_average,
        trailer_url=movie.trailer_url,
        director=movie.director,
        cast=movie.cast or [],
        tagline=movie.tagline,
        backdrop_path=movie.backdrop_path,
        imdb_id=movie.imdb_id,
        match_score=scores.get(tmdb_id),
    )
