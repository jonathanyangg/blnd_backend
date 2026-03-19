from collections.abc import Generator

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import OpenAI
from sqlalchemy.orm import Session
from supabase import create_client

from app.config import settings
from app.database import SessionLocal

# Clients
supabase = create_client(settings.supabase_url, settings.supabase_key)
supabase_admin = create_client(settings.supabase_url, settings.supabase_service_key)
openai_client = OpenAI(api_key=settings.openai_api_key)

security = HTTPBearer()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_tmdb_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.tmdb_client


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


async def get_optional_user(request: Request) -> str | None:
    """Extract user ID from Bearer token if present, otherwise return None."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    try:
        user_response = supabase.auth.get_user(token)
        if not user_response or not user_response.user:
            return None
        return str(user_response.user.id)
    except Exception:
        return None
