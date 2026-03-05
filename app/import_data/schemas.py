from pydantic import BaseModel


class SeedStatusResponse(BaseModel):
    status: str


class ImportSummaryResponse(BaseModel):
    imported: int
    skipped: int
    failed: int
    failed_titles: list[str]
