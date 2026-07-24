"""AI analysis Pydantic schemas."""

from datetime import datetime
from enum import Enum

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
    price: float | None = None
    change_percent: float | None = None
    market_cap: int | None = None
    pe_ratio: float | None = None
    forward_pe: float | None = None
    eps_ttm: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    week_52_high: float | None = None
    week_52_low: float | None = None
    sector: str | None = None
    industry: str | None = None


class RatioContext(BaseModel):
    """Context data for ratio analysis."""

    name: str
    numerator_symbol: str
    denominator_symbol: str
    current_value: float | None = None
    change_1d: float | None = None
    change_1m: float | None = None
    description: str | None = None


class WatchlistHolding(BaseModel):
    """A single watchlist member, condensed for AI context."""

    symbol: str
    name: str | None = None
    price: float | None = None
    change_percent: float | None = None
    target_price: float | None = None
    thesis: str | None = None


class WatchlistContext(BaseModel):
    """Context data for watchlist analysis."""

    name: str
    description: str | None = None
    holdings: list[WatchlistHolding] = []


class AIAnalysisRequest(BaseModel):
    """Request for AI analysis."""

    analysis_type: AnalysisType
    prompt: str = Field(..., min_length=1, max_length=2000)
    symbol: str | None = None  # For equity analysis
    ratio_id: int | None = None  # For ratio analysis
    watchlist_id: int | None = None  # For watchlist analysis
    # None → resolved server-side to the configured default (settings.AI_DEFAULT_MODEL).
    # This keeps the default configurable and un-hardcodable to an EOL id.
    model: AIModel | None = None
    include_context: bool = True


class AIAnalysisResponse(BaseModel):
    """Response from AI analysis."""

    analysis_type: AnalysisType
    prompt: str
    response: str
    model: str
    context_summary: str | None = None
    timestamp: datetime
    cached: bool = False  # True when served from the Redis response cache


class AISettingsResponse(BaseModel):
    """Response containing AI settings."""

    has_api_key: bool
    default_model: str
    custom_instructions: str | None = None


class AISettingsUpdate(BaseModel):
    """Request to update AI settings."""

    api_key: str | None = None
    default_model: str | None = None
    custom_instructions: str | None = None
