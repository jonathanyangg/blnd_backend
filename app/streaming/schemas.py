from pydantic import BaseModel


class StreamingPrice(BaseModel):
    amount: str
    currency: str
    formatted: str


class StreamingServiceInfo(BaseModel):
    id: str
    name: str
    logo_url: str | None = None


class StreamingOption(BaseModel):
    service: StreamingServiceInfo
    type: str  # "free" | "subscription" | "rent" | "buy" | "addon"
    link: str
    quality: str | None = None
    price: StreamingPrice | None = None
    expires_soon: bool = False


class StreamingAvailabilityResponse(BaseModel):
    tmdb_id: int
    country: str
    options: list[StreamingOption]
