"""Data providers package."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.data_providers.base import (
    MarketDataProvider,
    ProviderCapability,
)
from app.services.data_providers.finnhub import FinnhubNewsProvider
from app.services.data_providers.resilience import (
    FailoverQuoteProvider,
    ResilientProvider,
)
from app.services.data_providers.stooq import StooqProvider
from app.services.data_providers.yahoo import YahooFinanceProvider

logger = logging.getLogger(__name__)

__all__ = [
    "YahooFinanceProvider",
    "FinnhubNewsProvider",
    "MarketDataProvider",
    "ProviderCapability",
    "get_extended_quote_provider",
    "get_quote_provider",
    "reset_quote_provider",
]

# Process-level singleton so circuit-breaker state (failure counts, open/closed)
# persists across requests instead of resetting every time a service is built.
_quote_provider: FailoverQuoteProvider | None = None


def get_quote_provider() -> FailoverQuoteProvider:
    """Build (once) the resilient, failover-capable market-data provider.

    Sibling of ``get_extended_quote_provider``: *selection* lives here and the
    providers stay unaware of each other. The free chain is, in priority order:

      1. **Yahoo**, wrapped in retry + exponential backoff + circuit-breaker
         (``ResilientProvider``) — the primary for quote/history/fundamentals/
         search.
      2. **Stooq** (no API key) — quote + history fallback, itself wrapped so a
         flaky Stooq is retried/broken independently.
      3. **Alpha Vantage** — a quote fallback added *only* when
         ``ALPHA_VANTAGE_API_KEY`` is set (key-gated; inert otherwise).

    **A configured ``POLYGON_API_KEY`` promotes Massive (Polygon.io) to the
    front of that chain on every surface, and elects it as the quote primary.**
    A key is an explicit purchase of a better feed, so the paid source leads
    rather than backstops. Nothing about the free chain changes: without the
    key this function builds exactly the list above and elects nobody.

    Massive's Starter plan is 15-minute delayed, and the promotion deliberately
    does *not* pretend otherwise:

    - The quote still comes back ``stale=True`` (stamped by ``parse_snapshot``
      at the source), and the UI renders that provenance as a neutral
      "15-min delayed" label instead of a degraded-fallback warning.
    - The structural demotion in ``FailoverQuoteProvider`` is untouched and
      still the default. It is overridden only by the explicit ``quote_primary``
      election passed below, so a chain that puts a delayed provider first *by
      accident* is still corrected — the guard survives, it just now
      distinguishes an accident from a decision.
    - The election is an addition in front of the chain, so Yahoo remains the
      free chain's own head: when Massive cannot answer, Yahoo's quote is still
      reported fresh rather than badged as fallback data.

    Which of Massive's surfaces are usable is declared in
    ``MASSIVE_ENTITLEMENTS``; an unentitled surface raises
    ``ProviderUnentitledError`` *before the request leaves the process* and the
    chain routes past it exactly as it would past a failure, so an unowned
    surface costs nothing on the way to the free chain.

    A quote served by any fallback is stamped ``stale=True`` with its ``source``
    so the UI can show a degraded-data badge. Cached at module scope; call
    ``reset_quote_provider()`` in tests to get a fresh breaker.
    """
    global _quote_provider
    if _quote_provider is not None:
        return _quote_provider

    chain: list[MarketDataProvider] = [
        ResilientProvider(YahooFinanceProvider()),
        ResilientProvider(StooqProvider()),
    ]

    # Key-gated: only wire Alpha Vantage in when a free key is configured.
    try:
        from app.services.data_providers.alpha_vantage import (
            AlphaVantageProvider,
            is_alpha_vantage_configured,
        )

        if is_alpha_vantage_configured():
            chain.append(ResilientProvider(AlphaVantageProvider()))
            logger.info("Alpha Vantage fallback enabled (API key configured)")
    except Exception as exc:  # noqa: BLE001 — a bad optional provider must not break the chain
        logger.warning("Alpha Vantage fallback unavailable: %s", exc)

    # Key-gated, and PROMOTED TO THE FRONT: a configured key is an explicit
    # purchase of the paid feed, so Massive leads every surface. Quotes need the
    # election as well as the position — the delayed demotion in
    # ``FailoverQuoteProvider`` outranks list order by design, and only an
    # explicit ``quote_primary`` yields to intent.
    quote_primary: MarketDataProvider | None = None
    try:
        from app.services.data_providers.massive import (
            MassiveProvider,
            is_massive_configured,
        )

        if is_massive_configured():
            massive = MassiveProvider()
            # One object, used as both the chain member and the election — the
            # chain checks identity, so a second instance would never be
            # consulted.
            quote_primary = ResilientProvider(massive)
            chain.insert(0, quote_primary)
            logger.info(
                "Massive (Polygon.io) provider enabled (API key configured) and "
                "elected PRIMARY on every surface; its quotes are 15-minute "
                "delayed and are labelled as such rather than ranked below the "
                "free chain. Entitled surfaces: %s (MASSIVE_ENTITLEMENTS) — "
                "anything else routes to the next provider",
                massive.entitlements.describe(),
            )
    except Exception as exc:  # noqa: BLE001 — a bad optional provider must not break the chain
        logger.warning("Massive provider unavailable: %s", exc)
        quote_primary = None

    _quote_provider = FailoverQuoteProvider(chain, quote_primary=quote_primary)
    return _quote_provider


def reset_quote_provider() -> None:
    """Drop the cached provider singleton (test hook / key-config change)."""
    global _quote_provider
    _quote_provider = None


async def get_extended_quote_provider(db: AsyncSession):
    """Pick the extended-hours quote provider for briefings.

    **A configured ``POLYGON_API_KEY`` promotes Massive to the front of this
    chain too (BS10) — the extended-hours sibling of ``get_quote_provider``'s
    regular-quote promotion.** ``_get_base_extended_provider`` below computes
    exactly what this function used to return on its own (Yahoo, or Schwab
    when its own separate opt-in is on — see its docstring for that seam in
    full); when Massive is configured, this function wraps that result as the
    per-symbol fallback behind a ``MassiveExtendedQuoteProvider`` instead of
    returning it directly. Unconfigured, this function returns exactly what
    ``_get_base_extended_provider`` returns — unwrapped, same object, same
    type — so a keyless install (or any install before BS10) sees no change
    at all.

    Massive's quotes are 15-minute delayed on the Starter plan, same as the
    regular chain, and the same honesty rule applies: every quote Massive
    serves here is stamped ``source="massive"``/``stale=True`` (see
    ``MassiveProvider.get_extended_quote``) rather than presented as live.
    Deliberately **not** a promotion of ``get_quote_provider``'s real-time
    chain — that seam is untouched by this function and by this row.

    A bad/erroring Massive falls through **per symbol** to the fallback
    (``MassiveExtendedQuoteProvider``), matching ``SchwabProvider``'s existing
    per-symbol fallback shape — one Massive hiccup never blanks a briefing
    section that would otherwise have an answer.
    """
    base = await _get_base_extended_provider(db)

    try:
        from app.services.data_providers.massive import (
            MassiveExtendedQuoteProvider,
            MassiveProvider,
            is_massive_configured,
        )

        if is_massive_configured():
            massive = MassiveProvider()
            logger.info(
                "Massive (Polygon.io) elected primary for extended-hours "
                "quotes (POLYGON_API_KEY configured); falling back to %s "
                "per symbol",
                getattr(base, "name", type(base).__name__),
            )
            return MassiveExtendedQuoteProvider(massive, fallback=base)
    except Exception as exc:  # noqa: BLE001 — a bad optional provider must not break extended-hours quotes
        logger.warning("Massive extended-quote provider unavailable: %s", exc)

    return base


async def _get_base_extended_provider(db: AsyncSession):
    """Yahoo-or-Schwab half of extended-hours selection — Massive-unaware.

    **Yahoo by default, including when Schwab is connected (#273).** Schwab's
    quote role is opt-in and default-off (``SCHWAB_QUOTES_ENABLED``): a Schwab
    connection exists to ingest transactions and positions — the one thing no
    market-data vendor sells — and wiring it into the quote chain as well only
    handed a hard 7-day token expiry a blast radius over prices. Yahoo already
    serves every surface below, and futures/forex/indices never reached Schwab
    anyway (``_SCHWAB_SYMBOL_RE`` delegates them per-symbol).

    THIS IS THE ONE SEAM THE FLAG MOVES, and it has three consumers — flipping
    it re-sources all three, not just the movers:

    1. ``tasks/alerts.py`` — the morning-pulse and EOD-wrap extended-hours
       movers, via ``collect_extended_movers`` (reads ``session`` +
       ``change_percent``).
    2. ``services/agents/strategy_brief.py`` — the brief's extended-hours quote
       block, up to ``MAX_QUOTE_SYMBOLS`` (30) symbols; unlike the movers it
       consumes ``price``, so provider differences show up in the brief's
       numbers directly.
    3. ``scripts/premarket_pulse.py`` — the morning-brief market block.

    With the opt-in ON, selection is exactly what it always was: Schwab when
    the server is configured for it AND a user has connected a still-valid
    token; otherwise the free Yahoo base. Schwab remains opt-in depth — any
    missing piece degrades silently to Yahoo, never an error. Returns an
    ExtendedQuoteProvider (see app.services.extended_movers).

    Deliberately NOT the seam ingestion uses:
    ``schwab_ingestion.get_connected_provider`` builds its own Schwab client
    and is untouched by this flag — turning quotes off never turns sync off.
    """
    # Lazy import: schwab-py drags in heavy dependencies, and most installs
    # never configure it.
    from app.services.data_providers.schwab import (
        SchwabProvider,
        is_schwab_configured,
        parse_wrapped_token,
        schwab_quotes_enabled,
        token_is_expired,
    )

    yahoo = YahooFinanceProvider()

    if not schwab_quotes_enabled():
        # Not a failure and not worth a per-call log line: this is the default
        # posture, and briefings run this on every alert sweep.
        logger.debug(
            "Schwab quote role is off (SCHWAB_QUOTES_ENABLED); "
            "using Yahoo for extended-hours quotes"
        )
        return yahoo

    if not is_schwab_configured():
        return yahoo

    try:
        from app.services.settings import SettingsService

        service = SettingsService(db)
        user_id = await service.get_owner_user_id()
        raw_token = (
            await service.get_setting(SettingsService.SCHWAB_TOKEN, user_id)
            if user_id is not None
            else None
        )
    except Exception as e:
        logger.warning(f"Could not load Schwab token, using Yahoo: {e}")
        return yahoo

    wrapped = parse_wrapped_token(raw_token)
    if wrapped is None:
        return yahoo

    if token_is_expired(wrapped):
        logger.info(
            "Schwab token past its 7-day expiry; using Yahoo until reconnected"
        )
        return yahoo

    logger.info("Using Schwab for extended-hours quotes")
    return SchwabProvider(db, user_id, wrapped, fallback=yahoo)
