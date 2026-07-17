"""AI analysis service using Claude API."""

import hashlib
import logging
import uuid
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
    WatchlistContext,
    WatchlistHolding,
)
from app.services.ai_budget import token_budget
from app.services.cache import cache_service
from app.services.equity import EquityService
from app.services.ratio import RatioService
from app.services.settings import SettingsService
from app.services.watchlist import WatchlistService

logger = logging.getLogger(__name__)

# Setting keys owned by the AI service. The API *key* is NOT stored here — it is
# converged onto SettingsService.CLAUDE_API_KEY (encrypted, per-user) so the read
# and both write paths share one encrypted source of truth (see get_api_key).
SETTING_DEFAULT_MODEL = "ai_default_model"
SETTING_CUSTOM_INSTRUCTIONS = "ai_custom_instructions"

MAX_TOKENS = 2048


def _decimal_to_float(value) -> Optional[float]:
    """Convert Decimal to float safely."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


class AIService:
    """Service for AI-powered analysis using Claude API."""

    def __init__(
        self,
        db: AsyncSession,
        user_id: Optional[uuid.UUID] = None,
        *,
        cache=None,
        budget=None,
    ) -> None:
        self.db = db
        self.user_id = user_id
        # Collaborators default to the module singletons but are injectable for tests.
        self._cache = cache if cache is not None else cache_service
        self._budget = budget if budget is not None else token_budget
        self._settings_service = SettingsService(db)

    async def get_api_key(self) -> Optional[str]:
        """Get the Claude API key through the shared encrypted accessor.

        Reads ``CLAUDE_API_KEY`` via SettingsService, which decrypts values in
        ``ENCRYPTED_KEYS`` — the same accessor the Settings page and the AI
        settings endpoint write through. Falls back to the app-level env key.
        """
        key = await self._settings_service.get_setting(
            SettingsService.CLAUDE_API_KEY, self.user_id
        )
        if key:
            return key

        # Fall back to environment variable (app-level, not per-user).
        return settings.CLAUDE_API_KEY or None

    async def get_settings(self) -> AISettingsResponse:
        """Get current AI settings."""
        api_key = await self.get_api_key()

        # Get default model
        stmt = select(UserSetting).where(UserSetting.key == SETTING_DEFAULT_MODEL)
        result = await self.db.execute(stmt)
        model_setting = result.scalar_one_or_none()
        default_model = (
            model_setting.value if model_setting else settings.AI_DEFAULT_MODEL
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
            # Route the key write through the SAME encrypted accessor used for
            # reads (and by the Settings page), so both endpoints stay converged.
            if data.api_key == "":
                await self._settings_service.delete_setting(
                    SettingsService.CLAUDE_API_KEY, self.user_id
                )
            else:
                await self._settings_service.set_setting(
                    SettingsService.CLAUDE_API_KEY,
                    data.api_key,
                    self.user_id,
                    "Claude API key for AI analysis",
                )

        if data.default_model is not None:
            await self._upsert_setting(SETTING_DEFAULT_MODEL, data.default_model)

        if data.custom_instructions is not None:
            await self._upsert_setting(
                SETTING_CUSTOM_INSTRUCTIONS, data.custom_instructions
            )

        await self.db.commit()
        return await self.get_settings()

    async def _upsert_setting(self, key: str, value: str) -> None:
        """Insert or update a (non-secret) AI setting."""
        stmt = select(UserSetting).where(UserSetting.key == key)
        result = await self.db.execute(stmt)
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = value
        else:
            setting = UserSetting(key=key, value=value)
            self.db.add(setting)

    def _resolve_model(
        self, request: AIAnalysisRequest, default_model: Optional[str] = None
    ) -> AIModel:
        """Resolve the model to use.

        Precedence: explicit request model → the stored user default →
        ``settings.AI_DEFAULT_MODEL`` → Sonnet. Any unknown/retired id is
        skipped rather than passed to the API, so the default can never resolve
        to an EOL model.
        """
        candidates = [
            request.model.value if request.model else None,
            default_model,
            settings.AI_DEFAULT_MODEL,
            AIModel.CLAUDE_SONNET.value,
        ]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                return AIModel(candidate)
            except ValueError:
                logger.warning("Ignoring unknown AI model id: %s", candidate)
        return AIModel.CLAUDE_SONNET

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
        ratio_service = RatioService(self.db, self.user_id)
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

    async def _get_watchlist_context(
        self, watchlist_id: int
    ) -> Optional[WatchlistContext]:
        """Build context for watchlist analysis."""
        watchlist_service = WatchlistService(self.db, self.user_id)
        watchlist = await watchlist_service.get_watchlist(watchlist_id)

        if not watchlist:
            return None

        holdings = [
            WatchlistHolding(
                symbol=item.equity.symbol,
                name=item.equity.name,
                price=_decimal_to_float(item.quote.price) if item.quote else None,
                change_percent=_decimal_to_float(item.quote.change_percent)
                if item.quote
                else None,
                target_price=_decimal_to_float(item.target_price),
                thesis=item.thesis,
            )
            for item in watchlist.items
        ]

        return WatchlistContext(
            name=watchlist.name,
            description=watchlist.description,
            holdings=holdings,
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

    def _format_value(
        self, value, fmt: str = ".2f", prefix: str = "", suffix: str = ""
    ) -> str:
        """Format a value with proper null handling."""
        if value is None:
            return "N/A"
        return f"{prefix}{value:{fmt}}{suffix}"

    def _build_equity_prompt(
        self, user_prompt: str, context: EquityContext
    ) -> str:
        """Build the full prompt for equity analysis."""
        # Format values with proper null handling
        price_str = self._format_value(context.price, ".2f", "$")
        change_str = self._format_value(context.change_percent, ".2f", "", "%")
        low_52_str = self._format_value(context.week_52_low, ".2f", "$")
        high_52_str = self._format_value(context.week_52_high, ".2f", "$")
        market_cap_str = self._format_value(context.market_cap, ",", "$") if context.market_cap else "N/A"
        pe_str = self._format_value(context.pe_ratio, ".2f")
        forward_pe_str = self._format_value(context.forward_pe, ".2f")
        eps_str = self._format_value(context.eps_ttm, ".2f", "$")
        beta_str = self._format_value(context.beta, ".2f")
        div_yield_str = self._format_value(
            context.dividend_yield * 100 if context.dividend_yield else None, ".2f", "", "%"
        )

        context_str = f"""
Analyzing: {context.symbol} - {context.name}
Sector: {context.sector or 'N/A'}
Industry: {context.industry or 'N/A'}

Current Data:
- Price: {price_str}
- Day Change: {change_str}
- 52-Week Range: {low_52_str} - {high_52_str}

Valuation:
- Market Cap: {market_cap_str}
- P/E Ratio: {pe_str}
- Forward P/E: {forward_pe_str}
- EPS (TTM): {eps_str}

Risk Metrics:
- Beta: {beta_str}
- Dividend Yield: {div_yield_str}
"""

        return f"""Here is the current data for {context.symbol}:

{context_str}

User's question: {user_prompt}

Please provide a thoughtful analysis addressing the user's question."""

    def _build_ratio_prompt(
        self, user_prompt: str, context: RatioContext
    ) -> str:
        """Build the full prompt for ratio analysis."""
        # Format values with proper null handling
        current_val_str = self._format_value(context.current_value, ".4f")
        change_1d_str = self._format_value(context.change_1d, ".4f")
        change_1m_str = self._format_value(context.change_1m, ".4f")

        context_str = f"""
Ratio: {context.name}
Formula: {context.numerator_symbol} / {context.denominator_symbol}
Description: {context.description or 'N/A'}

Current Data:
- Current Value: {current_val_str}
- 1-Day Change: {change_1d_str}
- 1-Month Change: {change_1m_str}
"""

        return f"""Here is the current data for the {context.name} ratio:

{context_str}

User's question: {user_prompt}

Please provide analysis of this ratio and its implications."""

    def _build_watchlist_prompt(
        self, user_prompt: str, context: WatchlistContext
    ) -> str:
        """Build the full prompt for watchlist analysis."""
        if context.holdings:
            lines = []
            for h in context.holdings:
                price_str = self._format_value(h.price, ".2f", "$")
                change_str = self._format_value(h.change_percent, ".2f", "", "%")
                target_str = self._format_value(h.target_price, ".2f", "$")
                label = f"{h.symbol}" + (f" ({h.name})" if h.name else "")
                line = f"- {label}: {price_str} ({change_str}), target {target_str}"
                if h.thesis:
                    line += f" — thesis: {h.thesis}"
                lines.append(line)
            holdings_str = "\n".join(lines)
        else:
            holdings_str = "(no holdings)"

        context_str = f"""
Watchlist: {context.name}
Description: {context.description or 'N/A'}

Holdings ({len(context.holdings)}):
{holdings_str}
"""

        return f"""Here is the current data for the "{context.name}" watchlist:

{context_str}

User's question: {user_prompt}

Please provide analysis across this watchlist addressing the user's question."""

    async def _build_prompt_and_context(
        self, request: AIAnalysisRequest
    ) -> tuple[str, Optional[str]]:
        """Resolve the rendered user prompt and a short context summary.

        Handles all four analysis types explicitly. EQUITY/RATIO/WATCHLIST fetch
        and inline live context; GENERAL is a deliberately context-less mode that
        sends the raw prompt. No type falls through silently.
        """
        user_prompt = request.prompt
        context_summary: Optional[str] = None

        if not request.include_context:
            return user_prompt, context_summary

        if request.analysis_type == AnalysisType.EQUITY and request.symbol:
            context = await self._get_equity_context(request.symbol)
            if context:
                user_prompt = self._build_equity_prompt(request.prompt, context)
                context_summary = f"{context.symbol} - {context.name}"

        elif request.analysis_type == AnalysisType.RATIO and request.ratio_id:
            context = await self._get_ratio_context(request.ratio_id)
            if context:
                user_prompt = self._build_ratio_prompt(request.prompt, context)
                context_summary = (
                    f"{context.name} "
                    f"({context.numerator_symbol}/{context.denominator_symbol})"
                )

        elif request.analysis_type == AnalysisType.WATCHLIST and request.watchlist_id:
            context = await self._get_watchlist_context(request.watchlist_id)
            if context:
                user_prompt = self._build_watchlist_prompt(request.prompt, context)
                context_summary = f"Watchlist: {context.name} ({len(context.holdings)})"

        # AnalysisType.GENERAL: no context by design — raw prompt is sent as-is.
        return user_prompt, context_summary

    def _cache_signature(
        self, model: AIModel, system_prompt: str, user_prompt: str
    ) -> str:
        """Stable signature for the response cache.

        Identical (user, model, system, rendered prompt) → identical cache key.
        Scoped by user so one user's cached analysis is never served to another.
        """
        raw = "\x00".join(
            [str(self.user_id), model.value, system_prompt, user_prompt]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

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

        ai_settings = await self.get_settings()
        model = self._resolve_model(request, ai_settings.default_model)
        system_prompt = self._build_system_prompt(ai_settings.custom_instructions)
        user_prompt, context_summary = await self._build_prompt_and_context(request)

        signature = self._cache_signature(model, system_prompt, user_prompt)
        cache_key = self._cache.ai_response_key(signature)

        # Cache hit: return immediately (costs no tokens, skips the budget).
        cached = await self._cache_get(cache_key)
        if cached is not None:
            cached["cached"] = True
            return AIAnalysisResponse(**cached)

        # Fail closed if the per-day token budget is exhausted.
        await self._budget.check(self.user_id)

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model.value,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        response_text = message.content[0].text if message.content else ""
        await self._budget.record(self.user_id, _usage_tokens(message))

        response = AIAnalysisResponse(
            analysis_type=request.analysis_type,
            prompt=request.prompt,
            response=response_text,
            model=model.value,
            context_summary=context_summary,
            timestamp=datetime.utcnow(),
            cached=False,
        )
        await self._cache_set(cache_key, response)
        return response

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

        ai_settings = await self.get_settings()
        model = self._resolve_model(request, ai_settings.default_model)
        system_prompt = self._build_system_prompt(ai_settings.custom_instructions)
        user_prompt, _ = await self._build_prompt_and_context(request)

        signature = self._cache_signature(model, system_prompt, user_prompt)
        cache_key = self._cache.ai_response_key(signature)

        # Cache hit: replay the stored text as a single chunk (no tokens spent).
        cached = await self._cache_get(cache_key)
        if cached is not None and cached.get("response"):
            yield cached["response"]
            return

        # Fail closed if the per-day token budget is exhausted.
        await self._budget.check(self.user_id)

        client = anthropic.Anthropic(api_key=api_key)
        chunks: list[str] = []
        with client.messages.stream(
            model=model.value,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            for text in stream.text_stream:
                chunks.append(text)
                yield text
            final_message = stream.get_final_message()

        await self._budget.record(self.user_id, _usage_tokens(final_message))

        response = AIAnalysisResponse(
            analysis_type=request.analysis_type,
            prompt=request.prompt,
            response="".join(chunks),
            model=model.value,
            timestamp=datetime.utcnow(),
            cached=False,
        )
        await self._cache_set(cache_key, response)

    async def _cache_get(self, key: str) -> Optional[dict]:
        """Read a cached response; degrade gracefully on cache errors."""
        if settings.AI_RESPONSE_CACHE_TTL <= 0:
            return None
        try:
            return await self._cache.get(key)
        except Exception as exc:  # noqa: BLE001 - cache is best-effort
            logger.warning("AI response cache read failed: %s", exc)
            return None

    async def _cache_set(self, key: str, response: AIAnalysisResponse) -> None:
        """Store a response in the cache; degrade gracefully on cache errors."""
        if settings.AI_RESPONSE_CACHE_TTL <= 0:
            return
        try:
            await self._cache.set(
                key, response.model_dump(mode="json"), settings.AI_RESPONSE_CACHE_TTL
            )
        except Exception as exc:  # noqa: BLE001 - cache is best-effort
            logger.warning("AI response cache write failed: %s", exc)


def _usage_tokens(message) -> int:
    """Total (input + output) tokens for a Claude message, if reported."""
    usage = getattr(message, "usage", None)
    if usage is None:
        return 0
    return int(getattr(usage, "input_tokens", 0) or 0) + int(
        getattr(usage, "output_tokens", 0) or 0
    )
