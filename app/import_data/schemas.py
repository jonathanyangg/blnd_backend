from pydantic import BaseModel


class SeedStatusResponse(BaseModel):
    status: str
