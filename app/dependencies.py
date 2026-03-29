from collections.abc import Generator

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import OpenAI
from sqlalchemy.orm import Session
from supabase import create_client

from app.config import settings
from app.database import SessionLocal

# Clients
supabase = create_client(settings.supabase_url, settings.supabase_key)
openai_client = OpenAI(api_key=settings.openai_api_key)

# Admin client for privileged operations (e.g. account deletion, Apple token revocation)
# Uses service_role key which bypasses RLS. Created with default options
# since supabase-py 2.28.0 ClientOptions has a bug with persist_session=False.
supabase_admin = (
    create_client(settings.supabase_url, settings.supabase_service_key)
    if settings.supabase_service_key
    else None
)

security = HTTPBearer()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_tmdb_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.tmdb_client


_jwks_client = jwt.PyJWKClient(
    f"{settings.supabase_url}/auth/v1/.well-known/jwks.json",
    lifespan=3600,
)


def _decode_jwt(token: str) -> str:
    """Decode a Supabase JWT locally using JWKS and return the user ID (sub claim)."""
    signing_key = _jwks_client.get_signing_key_from_jwt(token)
    payload = jwt.decode(
        token,
        signing_key,
        algorithms=["ES256", "HS256"],
        audience="authenticated",
    )
    sub = payload.get("sub")
    if not sub:
        raise ValueError("Missing sub claim")
    return str(sub)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Verify JWT locally and return user ID."""
    try:
        return _decode_jwt(credentials.credentials)
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
    try:
        return _decode_jwt(auth[7:])
    except Exception:
        return None


async def require_admin(
    user_id: str = Depends(get_current_user),
) -> str:
    """FastAPI dependency that gates admin-only endpoints."""
    admin_ids: set[str] = {settings.admin_user_id} if settings.admin_user_id else set()
    if not admin_ids or user_id not in admin_ids:
        raise HTTPException(status_code=403, detail="Admin only")
    return user_id
