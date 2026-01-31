"""Pydantic schemas package."""

from app.schemas.common import (
    DataResponse,
    ErrorDetail,
    ErrorResponse,
    ListResponse,
    PaginatedMeta,
    ResponseMeta,
)
from app.schemas.equity import (
    EquityBase,
    EquityDetailResponse,
    EquitySearchResult,
    FundamentalsResponse,
    HistoryResponse,
    OHLCVData,
    QuoteResponse,
)

__all__ = [
    # Common
    "DataResponse",
    "ErrorDetail",
    "ErrorResponse",
    "ListResponse",
    "PaginatedMeta",
    "ResponseMeta",
    # Equity
    "EquityBase",
    "EquityDetailResponse",
    "EquitySearchResult",
    "FundamentalsResponse",
    "HistoryResponse",
    "OHLCVData",
    "QuoteResponse",
]
