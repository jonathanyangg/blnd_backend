from collections.abc import AsyncGenerator, Generator

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import OpenAI
from sqlalchemy.orm import Session
from supabase import create_client

from app.config import settings
from app.database import SessionLocal

# Clients
supabase = create_client(settings.supabase_url, settings.supabase_service_key)
openai_client = OpenAI(api_key=settings.openai_api_key)

security = HTTPBearer()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_tmdb_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        base_url="https://api.themoviedb.org/3",
        params={"api_key": settings.tmdb_api_key},
    ) as client:
        yield client


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Verify JWT via Supabase Auth and return user ID."""
    try:
        user_response = supabase.auth.get_user(credentials.credentials)
        if not user_response or not user_response.user:
            raise ValueError("No user found")
        return str(user_response.user.id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
