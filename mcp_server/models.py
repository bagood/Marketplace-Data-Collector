from typing import Any
from pydantic import BaseModel, Field

class AdsPage(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    has_more: bool

class DatasetMetadata(BaseModel):
    file: str
    delimiter: str
    columns: list[str]
    row_count: int
    sources: list[str]
    condition_ratings: list[str]

class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    dataset_available: bool
