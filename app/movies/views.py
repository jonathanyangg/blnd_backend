import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.rate_limit import LIMIT_DEFAULT, LIMIT_SEARCH, limiter
from app.dependencies import get_current_user, get_db, get_tmdb_client
from app.movies import schemas, services

router = APIRouter()


@router.get("/trending", response_model=schemas.MovieSearchResult)
@limiter.limit(LIMIT_DEFAULT)
async def get_trending_movies(
    request: Request,
    page: int = Query(default=1, ge=1),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    try:
        data = await services.get_trending_movies(page, tmdb_client)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="TMDB API error")

    tmdb_ids = [r["tmdb_id"] for r in data["results"]]
    scores = services.compute_match_scores(tmdb_ids, user_id, db)
    for r in data["results"]:
        r["match_score"] = scores.get(r["tmdb_id"])

    return data


@router.get("/discover", response_model=schemas.MovieSearchResult)
@limiter.limit(LIMIT_SEARCH)
async def discover_movies(
    request: Request,
    genres: str = Query(description="Comma-separated genre names"),
    page: int = Query(default=1, ge=1),
    _user_id: str = Depends(get_current_user),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    genre_list = [g.strip() for g in genres.split(",") if g.strip()]
    try:
        return await services.discover_movies_by_genres(genre_list, page, tmdb_client)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="TMDB API error")


@router.get("/search", response_model=schemas.MovieSearchResult)
@limiter.limit(LIMIT_SEARCH)
async def search_movies(
    request: Request,
    query: str = Query(min_length=1),
    page: int = Query(default=1, ge=1),
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
