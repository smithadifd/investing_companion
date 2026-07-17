"""AI analysis Pydantic schemas."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AnalysisType(str, Enum):
    """Types of AI analysis available."""

    EQUITY = "equity"
    RATIO = "ratio"
    WATCHLIST = "watchlist"
    GENERAL = "general"


class AIModel(str, Enum):
    """Supported Claude models.

    IDs are the current (non-EOL) lineup. The request-level default is *not*
    hardcoded here — it is resolved server-side from ``settings.AI_DEFAULT_MODEL``
    (see ``AIService._resolve_model``) so the default can be changed via env
    without a code change and can never silently point at a retired id.
    """

    CLAUDE_SONNET = "claude-sonnet-5"  # Sonnet 5 — best cost/capability (default)
    CLAUDE_OPUS = "claude-opus-4-8"  # Opus 4.8 — highest capability
    CLAUDE_HAIKU = "claude-haiku-4-5-20251001"  # Haiku 4.5 — cheapest


class EquityContext(BaseModel):
    """Context data for equity analysis."""

    symbol: str
    name: str
    price: Optional[float] = None
    change_percent: Optional[float] = None
    market_cap: Optional[int] = None
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    eps_ttm: Optional[float] = None
    dividend_yield: Optional[float] = None
    beta: Optional[float] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None


class RatioContext(BaseModel):
    """Context data for ratio analysis."""

    name: str
    numerator_symbol: str
    denominator_symbol: str
    current_value: Optional[float] = None
    change_1d: Optional[float] = None
    change_1m: Optional[float] = None
    description: Optional[str] = None


class WatchlistHolding(BaseModel):
    """A single watchlist member, condensed for AI context."""

    symbol: str
    name: Optional[str] = None
    price: Optional[float] = None
    change_percent: Optional[float] = None
    target_price: Optional[float] = None
    thesis: Optional[str] = None


class WatchlistContext(BaseModel):
    """Context data for watchlist analysis."""

    name: str
    description: Optional[str] = None
    holdings: list[WatchlistHolding] = []


class AIAnalysisRequest(BaseModel):
    """Request for AI analysis."""

    analysis_type: AnalysisType
    prompt: str = Field(..., min_length=1, max_length=2000)
    symbol: Optional[str] = None  # For equity analysis
    ratio_id: Optional[int] = None  # For ratio analysis
    watchlist_id: Optional[int] = None  # For watchlist analysis
    # None → resolved server-side to the configured default (settings.AI_DEFAULT_MODEL).
    # This keeps the default configurable and un-hardcodable to an EOL id.
    model: Optional[AIModel] = None
    include_context: bool = True


class AIAnalysisResponse(BaseModel):
    """Response from AI analysis."""

    analysis_type: AnalysisType
    prompt: str
    response: str
    model: str
    context_summary: Optional[str] = None
    timestamp: datetime
    cached: bool = False  # True when served from the Redis response cache


class AISettingsResponse(BaseModel):
    """Response containing AI settings."""

    has_api_key: bool
    default_model: str
    custom_instructions: Optional[str] = None


class AISettingsUpdate(BaseModel):
    """Request to update AI settings."""

    api_key: Optional[str] = None
    default_model: Optional[str] = None
    custom_instructions: Optional[str] = None
