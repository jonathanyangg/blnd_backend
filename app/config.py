import logging
import os

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Names only. Values are never logged.
REQUIRED_ENV_VARS = (
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_KEY",
    "DATABASE_URL",
    "REVENUECAT_WEBHOOK_SECRET",
)


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_service_key: str = ""
    database_url: str = ""
    tmdb_api_key: str = ""
    openai_api_key: str = ""
    admin_user_id: str = ""
    test_database_url: str = ""
    blnd_disable_rate_limits: str = ""
    apple_private_key: str = ""
    apple_key_id: str = ""
    apple_team_id: str = ""
    apple_bundle_id: str = ""
    apns_key: str = ""
    apns_key_id: str = ""
    apns_use_sandbox: str = ""
    digest_api_key: str = ""
    rapidapi_key: str = ""
    revenuecat_webhook_secret: str = ""
    anthropic_api_key: str = ""
    posthog_api_key: str = ""
    posthog_host: str = ""
    strict_env_validation: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()


def _strict_env_validation() -> bool:
    raw = os.environ.get("STRICT_ENV_VALIDATION", settings.strict_env_validation)
    return raw.strip().lower() == "true"


def missing_required_env_vars() -> list[str]:
    """Return required env var names whose settings values are empty."""
    missing: list[str] = []
    for name in REQUIRED_ENV_VARS:
        value = getattr(settings, name.lower(), "")
        if not str(value).strip():
            missing.append(name)
    return missing


def validate_required_settings() -> None:
    """Log missing required env vars. Raise only when STRICT_ENV_VALIDATION=true."""
    missing = missing_required_env_vars()
    if not missing:
        return
    logger.error("Missing required environment variables: %s", ", ".join(missing))
    if _strict_env_validation():
        raise RuntimeError(
            "STRICT_ENV_VALIDATION is true and required environment variables "
            f"are missing: {', '.join(missing)}"
        )
