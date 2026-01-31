"""Common response schemas."""

from datetime import datetime
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ResponseMeta(BaseModel):
    """Metadata included in all responses."""

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: Optional[str] = None


class DataResponse(BaseModel, Generic[T]):
    """Standard response wrapper for single items."""

    data: T
    meta: ResponseMeta = Field(default_factory=ResponseMeta)


class PaginatedMeta(ResponseMeta):
    """Metadata for paginated responses."""

    total: int
    page: int
    per_page: int
    pages: int


class ListResponse(BaseModel, Generic[T]):
    """Standard response wrapper for lists."""

    data: List[T]
    meta: PaginatedMeta


class ErrorDetail(BaseModel):
    """Error details structure."""

    code: str
    message: str
    details: Optional[dict[str, Any]] = None


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: ErrorDetail
