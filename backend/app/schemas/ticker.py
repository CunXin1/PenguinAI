from pydantic import BaseModel


class TickerResponse(BaseModel):
    ticker: str
    name: str
    exchange: str | None
    sector: str | None
    industry: str | None
    market_cap: int | None
    tags: list[str]
    is_active: bool

    model_config = {"from_attributes": True}


class TickerSearchResult(BaseModel):
    ticker: str
    name: str
    sector: str | None
    exchange: str | None
