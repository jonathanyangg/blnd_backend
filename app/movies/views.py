import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, get_tmdb_client
from app.movies import schemas, services

router = APIRouter()


@router.get("/trending", response_model=schemas.MovieSearchResult)
async def get_trending_movies(
    page: int = Query(default=1, ge=1),
    _user_id: str = Depends(get_current_user),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    try:
        return await services.get_trending_movies(page, tmdb_client)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="TMDB API error")


@router.get("/search", response_model=schemas.MovieSearchResult)
async def search_movies(
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
async def get_movie(
    tmdb_id: int,
    _user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    try:
        movie = await services.get_movie_details(tmdb_id, db, tmdb_client)
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
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Movie not found")
        raise HTTPException(status_code=e.response.status_code, detail="TMDB API error")
