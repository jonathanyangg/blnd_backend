from fastapi import APIRouter

router = APIRouter()


@router.post("/signup")
async def signup():
    return {"detail": "not implemented"}


@router.post("/login")
async def login():
    return {"detail": "not implemented"}


@router.get("/me")
async def me():
    return {"detail": "not implemented"}
