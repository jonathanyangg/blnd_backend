from fastapi import APIRouter

router = APIRouter()


@router.post("/letterboxd")
async def import_letterboxd():
    return {"imported": 0}
