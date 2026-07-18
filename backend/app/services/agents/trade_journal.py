"""Trade Journal & Pattern Analysis agent (T1 sub-PR 3/4, docs/issues/014).

Weekly behavioral-pattern review of closed trades: "you sold winners 3x
faster than losers", entry/exit quality commentary, a Discord summary.

Design (see the PR body for the full writeup):

* **Population** — closed trades = :class:`~app.db.models.trade.TradePair`
  rows whose ``close_trade.executed_at`` falls in ``[window_start,
  window_end)`` for the owner user. Lessons/notes are deliberately NOT
  incorporated (out of scope for this sub-PR).
* **Deterministic-first** — every number in ``metrics`` is computed in plain
  Python from those rows *before* any LLM call. The LLM only narrates; it
  never invents or restates different statistics.
* **metrics JSONB shape** (documented here since the model leaves it
  agent-owned)::

      {
        "pair_count": int,
        "matched_quantity": float,      # sum of TradePair.quantity_matched
        "realized_pnl": float,          # sum of TradePair.realized_pnl
        "wins": int,                    # realized_pnl > 0
        "losses": int,                  # realized_pnl < 0
        "breakeven": int,               # realized_pnl == 0
        "win_rate": float | None,       # wins / (wins + losses); null if 0
        "avg_hold_days_winners": float | None,  # qty-weighted, null if none
        "avg_hold_days_losers": float | None,   # qty-weighted, null if none
      }

* **Window** — ``[Monday 00:00 ET, next Monday 00:00 ET)`` containing "now"
  wall-clock, converted to UTC. The task is scheduled Sunday evening ET, so
  in practice this resolves to the week that just finished. ``window_end`` is
  the exclusive upper bound used directly in both the DB row and the closed-
  trade query, per the binding population rule.
* **Upsert** — one row per ``(user_id, window_start, window_end)``
  (``uq_trade_journal_user_window``); a re-run regenerates in place.
* **Zero closed trades** — no row written, no Discord message, INFO log.
* **LLM failure** — the row is still upserted with the deterministic metrics
  and a fixed-template fallback summary; Discord is skipped either way.
* **Discord rerun dedup** — on a re-run over an already-reviewed window,
  Discord is only re-sent when the summary or metrics actually changed
  from the stored row (an identical re-run sends nothing).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trade import Trade, TradePair
from app.db.models.trade_journal_entry import TradeJournalEntry
from app.schemas.ai import AIModel
from app.services.agents.base import AdvisoryAgent
from app.services.agents.guards import AgentFlag
from app.services.ai import AIService
from app.services.ai_budget import token_budget
from app.services.notifications.discord import discord_service

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Explicit ceiling on the weekly-review LLM call (S8 addendum item 8).
MAX_TOKENS = 1500

# Cap on individually itemized trades in the LLM prompt - a busy week's trade
# list is small in practice, but this keeps the prompt (and token spend)
# bounded regardless.
_MAX_PROMPT_TRADES = 40

DISCORD_CHAR_LIMIT = 2000

_SYSTEM_PROMPT = """You are a trading coach writing a trader's weekly closed-trade review.

You are given a set of statistics that were already computed deterministically
in Python - treat them as ground truth. Never invent, restate differently, or
contradict a number you were given; if you reference a figure, use exactly the
value provided.

Your job:
1. Narrate BEHAVIORAL PATTERNS visible in the data (e.g. "you sold winners
   faster than losers", "you cut losers quickly this week").
2. Give qualitative entry/exit QUALITY commentary - this is narrative
   judgment, not a new metric.

Rules:
- Never give a specific buy/sell recommendation.
- Never fabricate a statistic not present in the data you were given.
- Keep it concise - a few short paragraphs, suitable for a single Discord
  message."""


@dataclass(frozen=True)
class JournalWindow:
    """A half-open review window, both bounds tz-aware UTC."""

    start: datetime
    end: datetime


def compute_review_window(now: Optional[datetime] = None) -> JournalWindow:
    """The ``[Monday 00:00 ET, next Monday 00:00 ET)`` window containing ``now``.

    ``now`` defaults to the current time. The agent is scheduled to run
    Sunday evening ET (see ``celery_app.py``'s beat entry), so in practice
    this resolves to the week that just finished: this week's Monday through
    (but not including) next Monday.

    Arithmetic is done in ET wall-clock time and converted to UTC at the end
    so the window is correct across a DST transition that falls inside it
    (``zoneinfo`` recomputes the UTC offset from each datetime's own wall-clock
    fields, so simple timedelta arithmetic on an aware ``ZoneInfo`` datetime is
    safe here - no ``pytz``-style ``normalize()`` dance needed).
    """
    now = now if now is not None else datetime.now(timezone.utc)
    now_et = now.astimezone(ET)
    week_start_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=now_et.weekday()
    )
    week_end_et = week_start_et + timedelta(days=7)
    return JournalWindow(
        start=week_start_et.astimezone(timezone.utc),
        end=week_end_et.astimezone(timezone.utc),
    )


async def _closed_trade_pairs(
    db: AsyncSession, user_id: uuid.UUID, window: JournalWindow
) -> list[TradePair]:
    """TradePair rows closed within the window (binding population rule).

    "Closed" = ``close_trade.executed_at`` in ``[window.start, window.end)``.
    A partially-closing order contributes its matched pairs independently -
    each ``TradePair`` row already carries its own matched quantity and
    realized P&L, so no extra weighting is needed to avoid double counting.
    """
    stmt = (
        select(TradePair)
        .join(Trade, TradePair.close_trade_id == Trade.id)
        .where(
            TradePair.user_id == user_id,
            Trade.executed_at >= window.start,
            Trade.executed_at < window.end,
        )
        .order_by(Trade.executed_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _weighted_avg_hold_days(pairs: list[TradePair]) -> Optional[float]:
    """Quantity-weighted average holding period, or ``None`` when ``pairs`` is empty."""
    total_qty = sum((p.quantity_matched for p in pairs), Decimal("0"))
    if total_qty == 0:
        return None
    weighted = sum(
        (Decimal(p.holding_period_days) * p.quantity_matched for p in pairs), Decimal("0")
    )
    return float(weighted / total_qty)


def compute_metrics(pairs: list[TradePair]) -> dict:
    """Deterministic metrics for a window's closed trade pairs (see module docstring)."""
    matched_quantity = sum((p.quantity_matched for p in pairs), Decimal("0"))
    realized_pnl = sum((p.realized_pnl for p in pairs), Decimal("0"))

    wins = [p for p in pairs if p.realized_pnl > 0]
    losses = [p for p in pairs if p.realized_pnl < 0]
    breakeven = [p for p in pairs if p.realized_pnl == 0]

    denom = len(wins) + len(losses)
    win_rate = (len(wins) / denom) if denom > 0 else None

    return {
        "pair_count": len(pairs),
        "matched_quantity": float(matched_quantity),
        "realized_pnl": float(realized_pnl),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate": win_rate,
        "avg_hold_days_winners": _weighted_avg_hold_days(wins),
        "avg_hold_days_losers": _weighted_avg_hold_days(losses),
    }


def _fallback_summary(window: JournalWindow, metrics: dict) -> str:
    """Exact fallback template used when the LLM narrative is unavailable.

    The displayed end date is the window's INCLUSIVE last calendar day
    (``window.end`` minus one day) for human readability - ``window.end``
    itself stays the EXCLUSIVE next-Monday boundary everywhere else (the DB
    row and the closed-trade query), which this display-only shift does not
    touch.
    """
    display_end = window.end - timedelta(days=1)
    return (
        f"Week {window.start:%Y-%m-%d} – {display_end:%Y-%m-%d}: "
        f"{metrics['pair_count']} closed pairs, realized P&L {metrics['realized_pnl']}, "
        f"win rate {metrics['win_rate']}. (LLM narrative unavailable.)"
    )


def _build_prompt(window: JournalWindow, metrics: dict, pairs: list[TradePair]) -> str:
    """Render the user-turn prompt: computed numbers + a compact trade list."""
    lines = [
        f"Week under review: {window.start:%Y-%m-%d} to {window.end:%Y-%m-%d} (UTC bounds; "
        "the window is Monday 00:00 ET through the following Monday 00:00 ET).",
        "",
        "Computed metrics - ground truth, do not recompute or contradict:",
        f"- Closed pairs: {metrics['pair_count']}",
        f"- Matched quantity: {metrics['matched_quantity']}",
        f"- Realized P&L: {metrics['realized_pnl']}",
        f"- Wins / Losses / Breakeven: {metrics['wins']} / {metrics['losses']} / {metrics['breakeven']}",
        f"- Win rate: {metrics['win_rate']}",
        f"- Avg hold days, winners (qty-weighted): {metrics['avg_hold_days_winners']}",
        f"- Avg hold days, losers (qty-weighted): {metrics['avg_hold_days_losers']}",
        "",
        "Individual closed trades this week:",
    ]
    for p in pairs[:_MAX_PROMPT_TRADES]:
        symbol = p.equity.symbol if p.equity else "?"
        opened = p.open_trade.executed_at.date() if p.open_trade else "?"
        closed = p.close_trade.executed_at.date() if p.close_trade else "?"
        lines.append(
            f"- {symbol}: qty {p.quantity_matched}, held {p.holding_period_days}d, "
            f"P&L {p.realized_pnl}, opened {opened}, closed {closed}"
        )
    remainder = len(pairs) - _MAX_PROMPT_TRADES
    if remainder > 0:
        lines.append(f"...and {remainder} more closed pair(s) not itemized above.")
    lines.append("")
    lines.append(
        "Write the weekly review: (1) a behavioral-pattern narrative grounded in the "
        "numbers above, (2) qualitative entry/exit quality commentary. Introduce no new "
        "statistics."
    )
    return "\n".join(lines)


def _usage_tokens(message) -> int:
    """Total (input + output) tokens for a Claude message, if reported.

    Mirrors ``app.services.ai._usage_tokens`` - duplicated locally (four
    lines) rather than imported, since that helper is module-private to
    ``ai.py``.
    """
    usage = getattr(message, "usage", None)
    if usage is None:
        return 0
    return int(getattr(usage, "input_tokens", 0) or 0) + int(
        getattr(usage, "output_tokens", 0) or 0
    )


def _truncate_for_discord(message: str) -> str:
    """Truncate to Discord's 2000-char limit (same technique as formatters.py's ``_truncate``)."""
    if len(message) <= DISCORD_CHAR_LIMIT:
        return message
    return message[: DISCORD_CHAR_LIMIT - 3] + "..."


def _build_discord_message(window: JournalWindow, summary: str) -> str:
    header = f"**\U0001f4d3 Trade Journal — week of {window.start:%Y-%m-%d}**\n\n"
    return _truncate_for_discord(header + summary)


async def _get_existing_entry(
    db: AsyncSession, user_id: uuid.UUID, window: JournalWindow
) -> Optional[TradeJournalEntry]:
    stmt = select(TradeJournalEntry).where(
        TradeJournalEntry.user_id == user_id,
        TradeJournalEntry.window_start == window.start,
        TradeJournalEntry.window_end == window.end,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _upsert_entry(
    db: AsyncSession,
    user_id: uuid.UUID,
    window: JournalWindow,
    summary: str,
    metrics: dict,
) -> None:
    """Insert or update the one row for this ``(user_id, window)`` (never accumulate)."""
    stmt = pg_insert(TradeJournalEntry).values(
        user_id=user_id,
        window_start=window.start,
        window_end=window.end,
        summary=summary,
        metrics=metrics,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "window_start", "window_end"],
        set_={
            "summary": stmt.excluded.summary,
            "metrics": stmt.excluded.metrics,
            # Core-level upsert bypasses the ORM unit-of-work, so
            # TimestampMixin's onupdate=func.now() never fires here - set it
            # explicitly.
            "updated_at": func.now(),
        },
    )
    await db.execute(stmt)


class TradeJournalAgent(AdvisoryAgent):
    """Weekly behavioral-pattern review of closed trades (docs/issues/014 #2)."""

    name = "trade_journal"
    agent_flag: AgentFlag = "trade_journal_agent_enabled"

    async def execute(self, db: AsyncSession, user_id: Optional[uuid.UUID]) -> None:
        """Compute the review, upsert it, and send Discord if the content changed.

        Assumes the caller has already run :meth:`guard` and only calls this
        when allowed - this method does not re-check the enable flag, key, or
        budget itself (only the LLM call re-fetches the key, per the API-key
        pattern below).
        """
        if user_id is None:
            logger.info("trade_journal agent: no user_id resolved, skipping")
            return

        window = compute_review_window()
        pairs = await _closed_trade_pairs(db, user_id, window)
        if not pairs:
            logger.info(
                "trade_journal agent: no closed trades for user %s in window %s..%s, skipping",
                user_id,
                window.start.isoformat(),
                window.end.isoformat(),
            )
            return

        metrics = compute_metrics(pairs)
        existing = await _get_existing_entry(db, user_id, window)

        summary, llm_ok = await self._compose_summary(db, user_id, window, metrics, pairs)

        await _upsert_entry(db, user_id, window, summary, metrics)
        await db.commit()

        if not llm_ok:
            logger.warning(
                "trade_journal agent: LLM narrative unavailable for user %s, "
                "upserted deterministic fallback, skipping Discord",
                user_id,
            )
            return

        if existing is not None and existing.summary == summary and existing.metrics == metrics:
            logger.info(
                "trade_journal agent: unchanged content for user %s window %s..%s, "
                "skipping Discord resend",
                user_id,
                window.start.isoformat(),
                window.end.isoformat(),
            )
            return

        message = _build_discord_message(window, summary)
        success, error = await discord_service.send_plain_text(message)
        if not success:
            logger.warning(
                "trade_journal agent: Discord send failed for user %s: %s", user_id, error
            )

    async def _compose_summary(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        window: JournalWindow,
        metrics: dict,
        pairs: list[TradePair],
    ) -> tuple[str, bool]:
        """Return ``(summary, llm_ok)``. Any LLM failure falls back to the fixed template."""
        fallback = _fallback_summary(window, metrics)

        ai_service = AIService(db, user_id)
        # Re-fetched here rather than threaded through from guard() - the key
        # is never stored on the instance or logged.
        api_key = await ai_service.get_api_key()
        if not api_key:
            logger.warning(
                "trade_journal agent: no API key available at execute time for user %s",
                user_id,
            )
            return fallback, False

        try:
            model = await self._resolve_model(ai_service)
            prompt = _build_prompt(window, metrics, pairs)
            narrative = await self._call_llm(api_key, model, prompt, user_id)
        except Exception as exc:  # noqa: BLE001 - any LLM failure degrades to fallback
            logger.warning(
                "trade_journal agent: LLM narrative generation failed for user %s: %s",
                user_id,
                exc,
            )
            return fallback, False

        if not narrative:
            logger.warning(
                "trade_journal agent: LLM returned an empty narrative for user %s", user_id
            )
            return fallback, False

        return narrative, True

    @staticmethod
    async def _resolve_model(ai_service: AIService) -> AIModel:
        """Per-user default model, the same precedence AIService uses (never hardcoded)."""
        ai_settings = await ai_service.get_settings()
        try:
            return AIModel(ai_settings.default_model)
        except ValueError:
            logger.warning(
                "trade_journal agent: unknown default model %r, falling back to Sonnet",
                ai_settings.default_model,
            )
            return AIModel.CLAUDE_SONNET

    @staticmethod
    async def _call_llm(api_key: str, model: AIModel, prompt: str, user_id: uuid.UUID) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model.value,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text if message.content else ""
        await token_budget.record(user_id, _usage_tokens(message))
        return text.strip()
