from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

SymbolStatus = Literal[
    "pending",
    "real_pending_ingest",
    "delisted",
    "rejected_junk",
    "ingested",
    "already_covered",
]


class SymbolRequestInput(BaseModel):
    symbol: str

    @field_validator("symbol")
    @classmethod
    def normalize(cls, v: str) -> str:
        return v.strip().upper()


class SymbolRequestResult(BaseModel):
    symbol: str
    status: SymbolStatus
    request_count: int
    message: str


class SymbolRequestRow(BaseModel):
    symbol: str
    request_count: int
    status: str
    resolved_name: str | None = None
    resolved_exchange: str | None = None
    note: str | None = None
    first_requested_at: datetime | None = None
    last_requested_at: datetime | None = None
    validated_at: datetime | None = None

    model_config = {"from_attributes": True}
