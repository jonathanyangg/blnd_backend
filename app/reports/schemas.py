from pydantic import BaseModel, Field


class ReportUserRequest(BaseModel):
    reported_user_id: str
    reason: str = Field(min_length=1, max_length=200)
