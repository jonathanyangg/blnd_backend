from pydantic_settings import BaseSettings


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

    model_config = {"env_file": ".env"}


settings = Settings()
