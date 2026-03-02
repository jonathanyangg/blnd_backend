from fastapi import APIRouter

router = APIRouter()


@router.get("/search")
async def search_movies(query: str):
    return {"results": [], "total_results": 0}


@router.get("/{tmdb_id}")
async def get_movie(tmdb_id: int):
    return {"tmdb_id": tmdb_id, "detail": "not implemented"}
