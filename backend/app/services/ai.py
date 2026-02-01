"""AI analysis service using Claude API."""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import AsyncGenerator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.user_settings import UserSetting
from app.schemas.ai import (
    AIAnalysisRequest,
    AIAnalysisResponse,
    AIModel,
    AISettingsResponse,
    AISettingsUpdate,
    AnalysisType,
    EquityContext,
    RatioContext,
)
from app.services.equity import EquityService
from app.services.ratio import RatioService

logger = logging.getLogger(__name__)

# Setting keys
SETTING_API_KEY = "claude_api_key"
SETTING_DEFAULT_MODEL = "ai_default_model"
SETTING_CUSTOM_INSTRUCTIONS = "ai_custom_instructions"


def _decimal_to_float(value) -> Optional[float]:
    """Convert Decimal to float safely."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


class AIService:
    """Service for AI-powered analysis using Claude API."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_api_key(self) -> Optional[str]:
        """Get Claude API key from settings or environment."""
        # First check user settings
        stmt = select(UserSetting).where(UserSetting.key == SETTING_API_KEY)
        result = await self.db.execute(stmt)
        setting = result.scalar_one_or_none()

        if setting and setting.value:
            return setting.value

        # Fall back to environment variable
        return settings.CLAUDE_API_KEY or None

    async def get_settings(self) -> AISettingsResponse:
        """Get current AI settings."""
        api_key = await self.get_api_key()

        # Get default model
        stmt = select(UserSetting).where(UserSetting.key == SETTING_DEFAULT_MODEL)
        result = await self.db.execute(stmt)
        model_setting = result.scalar_one_or_none()
        default_model = (
            model_setting.value if model_setting else AIModel.CLAUDE_SONNET.value
        )

        # Get custom instructions
        stmt = select(UserSetting).where(UserSetting.key == SETTING_CUSTOM_INSTRUCTIONS)
        result = await self.db.execute(stmt)
        instructions_setting = result.scalar_one_or_none()
        custom_instructions = (
            instructions_setting.value if instructions_setting else None
        )

        return AISettingsResponse(
            has_api_key=bool(api_key),
            default_model=default_model,
            custom_instructions=custom_instructions,
        )

    async def update_settings(self, data: AISettingsUpdate) -> AISettingsResponse:
        """Update AI settings."""
        if data.api_key is not None:
            await self._upsert_setting(SETTING_API_KEY, data.api_key, is_encrypted=True)

        if data.default_model is not None:
            await self._upsert_setting(SETTING_DEFAULT_MODEL, data.default_model)

        if data.custom_instructions is not None:
            await self._upsert_setting(
                SETTING_CUSTOM_INSTRUCTIONS, data.custom_instructions
            )

        await self.db.commit()
        return await self.get_settings()

    async def _upsert_setting(
        self, key: str, value: str, is_encrypted: bool = False
    ) -> None:
        """Insert or update a setting."""
        stmt = select(UserSetting).where(UserSetting.key == key)
        result = await self.db.execute(stmt)
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = value
            setting.is_encrypted = is_encrypted
        else:
            setting = UserSetting(key=key, value=value, is_encrypted=is_encrypted)
            self.db.add(setting)

    async def _get_equity_context(self, symbol: str) -> Optional[EquityContext]:
        """Build context for equity analysis."""
        equity_service = EquityService(self.db)
        detail = await equity_service.get_equity_detail(symbol)

        if not detail:
            return None

        return EquityContext(
            symbol=detail.symbol,
            name=detail.name,
            price=_decimal_to_float(detail.quote.price) if detail.quote else None,
            change_percent=_decimal_to_float(detail.quote.change_percent)
            if detail.quote
            else None,
            market_cap=detail.fundamentals.market_cap if detail.fundamentals else None,
            pe_ratio=_decimal_to_float(detail.fundamentals.pe_ratio)
            if detail.fundamentals
            else None,
            forward_pe=_decimal_to_float(detail.fundamentals.forward_pe)
            if detail.fundamentals
            else None,
            eps_ttm=_decimal_to_float(detail.fundamentals.eps_ttm)
            if detail.fundamentals
            else None,
            dividend_yield=_decimal_to_float(detail.fundamentals.dividend_yield)
            if detail.fundamentals
            else None,
            beta=_decimal_to_float(detail.fundamentals.beta)
            if detail.fundamentals
            else None,
            week_52_high=_decimal_to_float(detail.fundamentals.week_52_high)
            if detail.fundamentals
            else None,
            week_52_low=_decimal_to_float(detail.fundamentals.week_52_low)
            if detail.fundamentals
            else None,
            sector=detail.sector,
            industry=detail.industry,
        )

    async def _get_ratio_context(self, ratio_id: int) -> Optional[RatioContext]:
        """Build context for ratio analysis."""
        ratio_service = RatioService(self.db)
        history = await ratio_service.get_ratio_history(ratio_id, "1mo")

        if not history:
            return None

        return RatioContext(
            name=history.ratio.name,
            numerator_symbol=history.ratio.numerator_symbol,
            denominator_symbol=history.ratio.denominator_symbol,
            current_value=_decimal_to_float(history.current_value),
            change_1d=_decimal_to_float(history.change_1d),
            change_1m=_decimal_to_float(history.change_1m),
            description=history.ratio.description,
        )

    def _build_system_prompt(self, custom_instructions: Optional[str] = None) -> str:
        """Build the system prompt for Claude."""
        base_prompt = """You are an expert financial analyst assistant. Your role is to provide
insightful, balanced analysis of equities, ratios, and market data.

Guidelines:
- Be concise but thorough
- Present both bullish and bearish perspectives
- Cite specific data points when making claims
- Acknowledge uncertainty where appropriate
- Focus on fundamental and technical factors
- Consider macroeconomic context when relevant
- Avoid making specific buy/sell recommendations
- Remind users that this is analysis, not financial advice"""

        if custom_instructions:
            base_prompt += f"\n\nAdditional instructions from user:\n{custom_instructions}"

        return base_prompt

    def _build_equity_prompt(
        self, user_prompt: str, context: EquityContext
    ) -> str:
        """Build the full prompt for equity analysis."""
        context_str = f"""
Analyzing: {context.symbol} - {context.name}
Sector: {context.sector or 'N/A'}
Industry: {context.industry or 'N/A'}

Current Data:
- Price: ${context.price:.2f if context.price else 'N/A'}
- Day Change: {context.change_percent:.2f}% if context.change_percent else 'N/A'
- 52-Week Range: ${context.week_52_low:.2f if context.week_52_low else 'N/A'} - ${context.week_52_high:.2f if context.week_52_high else 'N/A'}

Valuation:
- Market Cap: ${context.market_cap:,} if context.market_cap else 'N/A'
- P/E Ratio: {context.pe_ratio:.2f if context.pe_ratio else 'N/A'}
- Forward P/E: {context.forward_pe:.2f if context.forward_pe else 'N/A'}
- EPS (TTM): ${context.eps_ttm:.2f if context.eps_ttm else 'N/A'}

Risk Metrics:
- Beta: {context.beta:.2f if context.beta else 'N/A'}
- Dividend Yield: {(context.dividend_yield * 100):.2f}% if context.dividend_yield else 'N/A'
"""

        return f"""Here is the current data for {context.symbol}:

{context_str}

User's question: {user_prompt}

Please provide a thoughtful analysis addressing the user's question."""

    def _build_ratio_prompt(
        self, user_prompt: str, context: RatioContext
    ) -> str:
        """Build the full prompt for ratio analysis."""
        context_str = f"""
Ratio: {context.name}
Formula: {context.numerator_symbol} / {context.denominator_symbol}
Description: {context.description or 'N/A'}

Current Data:
- Current Value: {context.current_value:.4f if context.current_value else 'N/A'}
- 1-Day Change: {context.change_1d:.4f if context.change_1d else 'N/A'}
- 1-Month Change: {context.change_1m:.4f if context.change_1m else 'N/A'}
"""

        return f"""Here is the current data for the {context.name} ratio:

{context_str}

User's question: {user_prompt}

Please provide analysis of this ratio and its implications."""

    async def analyze(self, request: AIAnalysisRequest) -> AIAnalysisResponse:
        """Perform AI analysis (non-streaming)."""
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            )

        api_key = await self.get_api_key()
        if not api_key:
            raise ValueError("Claude API key not configured")

        # Get custom instructions
        settings = await self.get_settings()

        # Build context and prompt based on analysis type
        context_summary = None
        user_prompt = request.prompt

        if request.analysis_type == AnalysisType.EQUITY and request.symbol:
            if request.include_context:
                context = await self._get_equity_context(request.symbol)
                if context:
                    user_prompt = self._build_equity_prompt(request.prompt, context)
                    context_summary = f"{context.symbol} - {context.name}"

        elif request.analysis_type == AnalysisType.RATIO and request.ratio_id:
            if request.include_context:
                context = await self._get_ratio_context(request.ratio_id)
                if context:
                    user_prompt = self._build_ratio_prompt(request.prompt, context)
                    context_summary = f"{context.name} ({context.numerator_symbol}/{context.denominator_symbol})"

        # Call Claude API
        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model=request.model.value,
            max_tokens=2048,
            system=self._build_system_prompt(settings.custom_instructions),
            messages=[{"role": "user", "content": user_prompt}],
        )

        response_text = message.content[0].text if message.content else ""

        return AIAnalysisResponse(
            analysis_type=request.analysis_type,
            prompt=request.prompt,
            response=response_text,
            model=request.model.value,
            context_summary=context_summary,
            timestamp=datetime.utcnow(),
        )

    async def analyze_stream(
        self, request: AIAnalysisRequest
    ) -> AsyncGenerator[str, None]:
        """Perform AI analysis with streaming response."""
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            )

        api_key = await self.get_api_key()
        if not api_key:
            raise ValueError("Claude API key not configured")

        # Get custom instructions
        ai_settings = await self.get_settings()

        # Build context and prompt based on analysis type
        user_prompt = request.prompt

        if request.analysis_type == AnalysisType.EQUITY and request.symbol:
            if request.include_context:
                context = await self._get_equity_context(request.symbol)
                if context:
                    user_prompt = self._build_equity_prompt(request.prompt, context)

        elif request.analysis_type == AnalysisType.RATIO and request.ratio_id:
            if request.include_context:
                context = await self._get_ratio_context(request.ratio_id)
                if context:
                    user_prompt = self._build_ratio_prompt(request.prompt, context)

        # Call Claude API with streaming
        client = anthropic.Anthropic(api_key=api_key)

        with client.messages.stream(
            model=request.model.value,
            max_tokens=2048,
            system=self._build_system_prompt(ai_settings.custom_instructions),
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield text
