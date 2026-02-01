"""AI analysis Pydantic schemas."""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class AnalysisType(str, Enum):
    """Types of AI analysis available."""

    EQUITY = "equity"
    RATIO = "ratio"
    WATCHLIST = "watchlist"
    GENERAL = "general"


class AIModel(str, Enum):
    """Supported AI models."""

    CLAUDE_SONNET = "claude-3-5-sonnet-20241022"
    CLAUDE_HAIKU = "claude-3-5-haiku-20241022"


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


class AIAnalysisRequest(BaseModel):
    """Request for AI analysis."""

    analysis_type: AnalysisType
    prompt: str = Field(..., min_length=1, max_length=2000)
    symbol: Optional[str] = None  # For equity analysis
    ratio_id: Optional[int] = None  # For ratio analysis
    watchlist_id: Optional[int] = None  # For watchlist analysis
    model: AIModel = AIModel.CLAUDE_SONNET
    include_context: bool = True


class AIAnalysisResponse(BaseModel):
    """Response from AI analysis."""

    analysis_type: AnalysisType
    prompt: str
    response: str
    model: str
    context_summary: Optional[str] = None
    timestamp: datetime


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
