from fastapi import APIRouter

router = APIRouter()


@router.get("/me")
async def get_recommendations():
    return {"recommendations": []}


@router.get("/group/{group_id}")
async def get_group_recommendations(group_id: int):
    return {"recommendations": []}
