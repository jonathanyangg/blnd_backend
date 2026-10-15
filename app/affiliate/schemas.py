from pydantic import BaseModel


class WatchOfferResponse(BaseModel):
    provider_id: int
    provider_name: str
    logo_path: str | None = None
    web_url: str
    app_url: str | None = None


class WhereToWatch(BaseModel):
    """Subscription, rent, and buy offers for one country."""

    country: str
    attribution: str
    link: str | None = None
    flatrate: list[WatchOfferResponse] = []
    rent: list[WatchOfferResponse] = []
    buy: list[WatchOfferResponse] = []
