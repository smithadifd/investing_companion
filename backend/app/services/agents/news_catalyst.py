"""News & Catalyst advisory agent (T1 sub-PR 2/4, docs/issues/014-intelligent-agents.md).

Ticket: "News & Catalyst Aggregator: Pull news/catalysts for watchlist items,
inject context into morning pulse and EOD wrap." This PR covers morning-pulse
injection only; EOD-wrap enrichment is a declared follow-up.

``execute()`` runs fetch -> persist -> score:

1. **Fetch**: Finnhub company news for each watchlist symbol (capped, see
   ``MAX_SYMBOLS_PER_RUN``) plus one general market-news call, throttled to
   respect Finnhub's free-tier rate limit (no rate limiting is built into
   :class:`FinnhubNewsProvider`).
2. **Persist**: new rows land in ``news_items``, deduplicated on ``url``
   (a select-first + per-row nested-savepoint insert, safe under a rare
   concurrent-insert race).
3. **Score**: one batched Claude call scores relevance (0..1) and writes a
   short summary for newly-inserted items (capped per run). Any LLM failure
   (call error or an unparseable response) leaves those items persisted but
   unscored rather than raising - the fetch/persist work is never lost.

Retention (pruning ``news_items`` older than 30 days) is intentionally NOT
part of ``execute()`` - it runs unconditionally from the Celery task
(``app/tasks/agent_news.py``) via :meth:`NewsCatalystAgent.prune_old_news`,
BEFORE the guard's early-exit paths, so bounded table growth doesn't depend
on the agent being enabled/keyed/within budget.

Advisory-only (hard rule): this agent reads market data and writes ONLY
``news_items``. No other tables, no mutating endpoints, no trades/watchlist
writes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.news_item import NewsItem
from app.schemas.ai import AIModel
from app.services.agents.base import AdvisoryAgent
from app.services.ai import AIService
from app.services.ai_budget import token_budget
from app.services.data_providers.finnhub import FinnhubNewsProvider
from app.services.watchlist import WatchlistService

logger = logging.getLogger(__name__)

# Bounded table growth - the task prunes rows older than this, unconditionally,
# before it even checks whether the agent is allowed to run this cycle.
RETENTION_DAYS = 30

# Cap how many watchlist symbols one run fetches news for (a large watchlist
# combined with Finnhub's free-tier 60 calls/min ceiling could otherwise make
# a single run take minutes). Overflow symbols are simply skipped this run;
# there is no rotation - the same head-of-list symbols win every run, which is
# an accepted simplification (a real rotation/priority scheme is a follow-up).
MAX_SYMBOLS_PER_RUN = 30

# No rate limiting is built into FinnhubNewsProvider (see its docstring); the
# free tier allows 60 calls/min, so >=1.1s of spacing between calls keeps a
# full 31-call run (30 symbols + 1 market-news call) safely under that.
FINNHUB_THROTTLE_SECONDS = 1.1

# How far back each Finnhub company-news call looks. Short window - this is a
# "what's new" catalyst feed, not a historical backfill.
NEWS_DAYS_BACK = 3

# LLM scoring bounds (binding addendum #4): explicit max_tokens on every call,
# and a hard cap on how many *new* articles one run will send to the model.
# Articles beyond the cap stay persisted (unscored) for a later run to pick up
# via a future re-score pass - they are not lost, just deferred.
LLM_MAX_TOKENS = 2000
MAX_ARTICLES_SCORED_PER_RUN = 50

# Per-item text sent to the model is truncated independently of the DB column
# widths (headline=500/summary=500) so a pathological single item can't blow
# out the batched prompt.
PROMPT_HEADLINE_CHARS = 500
PROMPT_SUMMARY_CHARS = 500

_SCORING_SYSTEM_PROMPT = (
    "You are a financial news triage assistant for an active stock-watchlist "
    "investor. You will be given a numbered list of news headlines (each "
    "tagged with the symbol it's about, or MARKET for general market news). "
    "For EACH item, score how relevant/actionable it is as a trading catalyst "
    "on a 0.0-1.0 scale (1.0 = major, market-moving catalyst; 0.0 = "
    "irrelevant noise) and write one punchy summary line (<=200 characters) "
    "capturing the catalyst in plain language.\n\n"
    "Respond with ONLY a JSON array, one object per input item, in the same "
    "order, no prose before or after:\n"
    '[{"index": <int>, "relevance": <float 0-1>, "summary": "<string>"}, ...]'
)


def _usage_tokens(message) -> int:
    """Total (input + output) tokens for a Claude message, if reported."""
    usage = getattr(message, "usage", None)
    if usage is None:
        return 0
    return int(getattr(usage, "input_tokens", 0) or 0) + int(
        getattr(usage, "output_tokens", 0) or 0
    )


def _parse_finnhub_timestamp(value) -> Optional[datetime]:
    """Convert a Finnhub Unix-epoch ``datetime`` field to a tz-aware UTC value.

    Deliberately NOT the ``app/services/news.py:_parse_finnhub_item`` precedent
    - that helper produces NAIVE datetimes via ``datetime.utcfromtimestamp``,
    which is wrong for a ``DateTime(timezone=True)`` column. Malformed/absent
    values return ``None`` so the caller can reject the item rather than
    persist a garbage timestamp.
    """
    if value is None:
        return None
    try:
        epoch = float(value)
    except (TypeError, ValueError):
        return None
    if epoch <= 0:
        return None
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _resolve_scoring_model(default_model: Optional[str]) -> str:
    """Resolve a Claude model id the same way ``AIService._resolve_model`` does.

    Never hardcodes a model id: prefers the per-user ``ai_default_model``
    setting, falls back to the app-level default, then the enum's current
    Sonnet id. An unknown/retired id (e.g. a stale per-user setting) is
    skipped rather than sent to the API.
    """
    for candidate in (default_model, settings.AI_DEFAULT_MODEL, AIModel.CLAUDE_SONNET.value):
        if not candidate:
            continue
        try:
            return AIModel(candidate).value
        except ValueError:
            logger.warning("news_catalyst: ignoring unknown AI model id: %s", candidate)
    return AIModel.CLAUDE_SONNET.value


def _parse_scoring_response(text: str, count: int) -> dict[int, tuple[float, str]]:
    """Best-effort parse of the batched scoring response.

    Returns ``{}`` on any malformed response (not valid JSON, not a list,
    wrong shape) - the caller treats that identically to a call failure and
    leaves the batch unscored rather than raising.
    """
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, list):
        return {}

    out: dict[int, tuple[float, str]] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= count:
            continue
        try:
            relevance = float(entry.get("relevance"))
        except (TypeError, ValueError):
            continue
        relevance = max(0.0, min(1.0, relevance))
        summary = entry.get("summary")
        summary_str = str(summary).strip() if summary is not None else ""
        out[idx] = (relevance, summary_str[:500])
    return out


class NewsCatalystAgent(AdvisoryAgent):
    """Fetches Finnhub news for watchlist symbols and scores it for the pulse."""

    name = "news_catalyst"
    agent_flag = "news_agent_enabled"

    def __init__(self, *, provider: Optional[FinnhubNewsProvider] = None) -> None:
        self._provider = provider or FinnhubNewsProvider()

    # ------------------------------------------------------------------
    # Retention - called directly by the task, NOT part of execute()/guard()
    # ------------------------------------------------------------------
    async def prune_old_news(self, db: AsyncSession) -> int:
        """Delete ``news_items`` older than ``RETENTION_DAYS``. Commits.

        Runs unconditionally (see module docstring) - independent of the
        enable flag, API key, or budget, so table growth stays bounded even
        for an agent that's disabled or misconfigured.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        result = await db.execute(delete(NewsItem).where(NewsItem.published_at < cutoff))
        await db.commit()
        return result.rowcount or 0

    # ------------------------------------------------------------------
    # execute() - only reached after guard() allows the run
    # ------------------------------------------------------------------
    async def execute(self, db: AsyncSession, user_id: Optional[uuid.UUID]) -> None:
        if not self._provider.is_configured:
            logger.info("news_catalyst: Finnhub not configured, quiet no-op")
            return

        symbols = await self._watchlist_symbols(db)
        if len(symbols) > MAX_SYMBOLS_PER_RUN:
            logger.info(
                "news_catalyst: capping %d watchlist symbols to %d for this run",
                len(symbols),
                MAX_SYMBOLS_PER_RUN,
            )
            symbols = symbols[:MAX_SYMBOLS_PER_RUN]

        parsed_items = await self._fetch_and_parse(symbols)
        new_items = await self._persist(db, parsed_items)

        if new_items:
            await self._score(db, user_id, new_items)

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------
    async def _watchlist_symbols(self, db: AsyncSession) -> list[str]:
        """Distinct symbols across every watchlist, first-seen order."""
        watchlist_service = WatchlistService(db)
        summaries = await watchlist_service.list_watchlists()
        seen: set[str] = set()
        symbols: list[str] = []
        for summary in summaries:
            wl = await watchlist_service.get_watchlist(summary.id, include_quotes=False)
            if not wl:
                continue
            for item in wl.items:
                symbol = item.equity.symbol
                if symbol and symbol not in seen:
                    seen.add(symbol)
                    symbols.append(symbol)
        return symbols

    async def _throttle(self) -> None:
        await asyncio.sleep(FINNHUB_THROTTLE_SECONDS)

    async def _fetch_and_parse(self, symbols: list[str]) -> list[dict]:
        """Fetch per-symbol + one general market-news call, parsed + filtered.

        Throttled to >=1.1s between Finnhub calls (its free tier has no
        built-in rate limiting). Malformed items (no url/headline, bad
        timestamp) are dropped here rather than persisted.
        """
        parsed: list[dict] = []
        call_count = 0

        for symbol in symbols:
            if call_count:
                await self._throttle()
            raw_items = await self._provider.get_company_news(symbol, days_back=NEWS_DAYS_BACK)
            call_count += 1
            for raw in raw_items:
                item = self._parse_raw_item(raw, symbol)
                if item:
                    parsed.append(item)

        if call_count:
            await self._throttle()
        market_items = await self._provider.get_market_news("general")
        for raw in market_items:
            item = self._parse_raw_item(raw, None)
            if item:
                parsed.append(item)

        return parsed

    @staticmethod
    def _parse_raw_item(raw: dict, symbol: Optional[str]) -> Optional[dict]:
        url = (raw.get("url") or "").strip()
        headline = (raw.get("headline") or "").strip()
        if not url or not headline:
            return None
        published_at = _parse_finnhub_timestamp(raw.get("datetime"))
        if published_at is None:
            return None
        source = (raw.get("source") or "Unknown").strip() or "Unknown"
        summary = raw.get("summary")
        summary = summary.strip() if isinstance(summary, str) and summary.strip() else None
        return {
            "symbol": symbol,
            "headline": headline[:500],
            "url": url[:2048],
            "source": source[:100],
            "published_at": published_at,
            "summary": summary[:2000] if summary else None,
        }

    # ------------------------------------------------------------------
    # Persist - dedup on url
    # ------------------------------------------------------------------
    async def _persist(self, db: AsyncSession, parsed_items: list[dict]) -> list[NewsItem]:
        if not parsed_items:
            return []

        # De-dup within this run's batch first (the same article can surface
        # from two different symbols' company-news calls).
        by_url: dict[str, dict] = {}
        for item in parsed_items:
            by_url.setdefault(item["url"], item)

        existing_urls = set(
            (
                await db.execute(select(NewsItem.url).where(NewsItem.url.in_(by_url.keys())))
            )
            .scalars()
            .all()
        )

        new_rows: list[NewsItem] = []
        for url, data in by_url.items():
            if url in existing_urls:
                continue
            row = NewsItem(**data)
            try:
                async with db.begin_nested():
                    db.add(row)
                    await db.flush()
            except IntegrityError:
                # Rare concurrent-insert race on the url unique index - the
                # other writer won, this one is a no-op dedup, not an error.
                logger.info("news_catalyst: dedup race on url, skipping: %s", url)
                continue
            new_rows.append(row)

        if new_rows:
            await db.commit()
        return new_rows

    # ------------------------------------------------------------------
    # Score - one batched LLM call for newly-inserted items
    # ------------------------------------------------------------------
    async def _score(
        self, db: AsyncSession, user_id: Optional[uuid.UUID], items: list[NewsItem]
    ) -> None:
        batch = items[:MAX_ARTICLES_SCORED_PER_RUN]
        overflow = len(items) - len(batch)
        if overflow > 0:
            logger.info(
                "news_catalyst: %d new articles left unscored this run (cap %d)",
                overflow,
                MAX_ARTICLES_SCORED_PER_RUN,
            )

        ai_service = AIService(db, user_id)
        # Same source the guard used (binding addendum #3) - execute() never
        # trusts a key handed to it from elsewhere, and never logs it.
        api_key = await ai_service.get_api_key()
        if not api_key:
            logger.info("news_catalyst: no API key at scoring time, leaving items unscored")
            return

        try:
            import anthropic
        except ImportError:
            logger.warning("news_catalyst: anthropic package not installed, leaving items unscored")
            return

        ai_settings = await ai_service.get_settings()
        model = _resolve_scoring_model(ai_settings.default_model)
        prompt = self._build_scoring_prompt(batch)

        try:
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model=model,
                max_tokens=LLM_MAX_TOKENS,
                system=_SCORING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001 - any LLM failure degrades quietly
            logger.warning("news_catalyst: LLM scoring call failed, leaving items unscored: %s", exc)
            return

        tokens = _usage_tokens(message)
        if tokens:
            await token_budget.record(user_id, tokens)

        response_text = message.content[0].text if message.content else ""
        parsed = _parse_scoring_response(response_text, len(batch))
        if not parsed:
            logger.info(
                "news_catalyst: scoring response unparseable, leaving %d items unscored",
                len(batch),
            )
            return

        for i, item in enumerate(batch):
            scored = parsed.get(i)
            if not scored:
                continue
            relevance, summary = scored
            item.relevance = relevance
            if summary:
                item.summary = summary
        await db.commit()

    @staticmethod
    def _build_scoring_prompt(items: list[NewsItem]) -> str:
        lines = ["Score these news items:"]
        for i, item in enumerate(items):
            headline = (item.headline or "")[:PROMPT_HEADLINE_CHARS]
            summary = (item.summary or "")[:PROMPT_SUMMARY_CHARS]
            tag = item.symbol or "MARKET"
            line = f"{i}. [{tag}] {headline}"
            if summary:
                line += f" — {summary}"
            lines.append(line)
        return "\n".join(lines)
