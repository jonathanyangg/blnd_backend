from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_service_key: str = ""
    database_url: str = ""
    tmdb_api_key: str = ""
    openai_api_key: str = ""
    test_database_url: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
