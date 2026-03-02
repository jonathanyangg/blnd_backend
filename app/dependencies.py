from typing import Generator

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


def get_tmdb_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.themoviedb.org/3",
        params={"api_key": settings.tmdb_api_key},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Verify JWT via Supabase Auth and return user ID."""
    try:
        user_response = supabase.auth.get_user(credentials.credentials)
        if user_response is None:
            raise ValueError("No user found")
        user = user_response.user
        if user is None:
            raise ValueError("No user found")
        return str(user.id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
