import logging
import time

import httpx
import jwt

from app.config import settings

logger = logging.getLogger(__name__)

APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
APPLE_REVOKE_URL = "https://appleid.apple.com/auth/revoke"


def generate_apple_client_secret() -> str:
    """Generate an ES256 JWT for Apple API authentication."""
    now = int(time.time())
    headers = {"kid": settings.apple_key_id, "alg": "ES256"}
    payload = {
        "iss": settings.apple_team_id,
        "iat": now,
        "exp": now + 300,
        "aud": "https://appleid.apple.com",
        "sub": settings.apple_bundle_id,
    }
    return jwt.encode(
        payload, settings.apple_private_key, algorithm="ES256", headers=headers
    )


async def exchange_apple_auth_code(authorization_code: str) -> str:
    """Exchange an Apple authorizationCode for a refresh_token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            APPLE_TOKEN_URL,
            data={
                "client_id": settings.apple_bundle_id,
                "client_secret": generate_apple_client_secret(),
                "code": authorization_code,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if response.status_code == 200:
        return response.json()["refresh_token"]

    logger.warning(
        "Apple token exchange failed: status=%d body=%s",
        response.status_code,
        response.text,
    )
    raise ValueError(f"Apple token exchange failed: {response.status_code}")


async def revoke_apple_token(refresh_token: str) -> bool:
    """Revoke an Apple refresh_token. Returns True on success."""
    client_secret = generate_apple_client_secret()
    async with httpx.AsyncClient() as client:
        response = await client.post(
            APPLE_REVOKE_URL,
            data={
                "client_id": settings.apple_bundle_id,
                "client_secret": client_secret,
                "token": refresh_token,
                "token_type_hint": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    return response.status_code == 200
