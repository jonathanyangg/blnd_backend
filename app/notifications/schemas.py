from pydantic import BaseModel


class RegisterDeviceRequest(BaseModel):
    token: str
    platform: str = "ios"


class MessageResponse(BaseModel):
    message: str


class PreferencesResponse(BaseModel):
    friend_requests: bool
    group_invites: bool
    recommendations: bool
    friend_activity: bool


class UpdatePreferencesRequest(BaseModel):
    friend_requests: bool | None = None
    group_invites: bool | None = None
    recommendations: bool | None = None
    friend_activity: bool | None = None


class DigestStatusResponse(BaseModel):
    status: str
