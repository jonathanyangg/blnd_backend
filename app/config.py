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
    revenuecat_webhook_secret: str = ""
    anthropic_api_key: str = ""
    posthog_api_key: str = ""
    posthog_host: str = ""
    tv_support_enabled: bool = False
    # None means unset: Amazon links use the public tag. "" means untagged.
    amazon_associates_tag: str | None = None
    amazon_associates_enabled: bool = True
    impact_enabled: bool = False
    impact_partner_id: str = ""
    rakuten_enabled: bool = False
    rakuten_partner_id: str = ""
    cj_enabled: bool = False
    cj_partner_id: str = ""
    apple_tv_affiliate_enabled: bool = False
    apple_tv_affiliate_token: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
