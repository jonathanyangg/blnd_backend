from pydantic import BaseModel, Field


class RevenueCatEvent(BaseModel):
    """Subset of the RevenueCat webhook event payload we care about.

    Full spec: https://www.revenuecat.com/docs/integrations/webhooks/event-types-and-fields
    """

    type: str
    id: str
    app_user_id: str
    product_id: str | None = None
    original_transaction_id: str | None = None
    expiration_at_ms: int | None = None
    environment: str | None = None
    store: str | None = None


class RevenueCatWebhookPayload(BaseModel):
    event: RevenueCatEvent
    api_version: str | None = Field(default=None, alias="api_version")


class SubscriptionStatusResponse(BaseModel):
    tier: str
    expires_at: str | None
    source: str | None
