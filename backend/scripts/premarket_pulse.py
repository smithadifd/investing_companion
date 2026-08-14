"""premarket_pulse.py — emit a pre-open market pulse for the morning brief.

Prints a single `### SOURCE: markets` block to stdout: the major index ETFs and
all 11 SPDR sector ETFs via the extended-hours quote provider (Yahoo premarket
prints by default, or Schwab's when a server sets SCHWAB_QUOTES_ENABLED and a
token is connected — honest "at close" either way when the session has no
data), plus a few non-futures macro tells (VIX, 10Y yield, dollar, BTC) that
Yahoo always serves. No equity-index/commodity *futures* — Schwab can't quote
them and Yahoo's are unreliable; premarket ETF prints are the dependable read.

Designed to be run inside the investing_api container, e.g. from the morning
brief on another host:

    ssh synology "... docker exec investing_api python /app/scripts/premarket_pulse.py"

Always exits 0 with a usable block (degrading per-symbol to "unavailable") so
the brief's fetcher can capture stdout directly.
"""

import asyncio
import sys
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.models.economic_event import EconomicEvent
from app.db.session import AsyncSessionLocal
from app.services.data_providers import get_extended_quote_provider

ET = ZoneInfo("America/New_York")
EVENTS_AHEAD_DAYS = 7

INDICES = [
    ("SPY", "S&P 500 (SPY)"),
    ("QQQ", "Nasdaq 100 (QQQ)"),
    ("DIA", "Dow (DIA)"),
    ("IWM", "Russell 2000 (IWM)"),
]
SECTORS = [
    ("XLK", "Technology"),
    ("XLF", "Financials"),
    ("XLV", "Healthcare"),
    ("XLE", "Energy"),
    ("XLY", "Consumer Disc."),
    ("XLP", "Consumer Staples"),
    ("XLI", "Industrials"),
    ("XLB", "Materials"),
    ("XLU", "Utilities"),
    ("XLRE", "Real Estate"),
    ("XLC", "Communications"),
]
MACRO = [
    ("^VIX", "VIX"),
    ("^TNX", "10Y yield"),
    ("DX-Y.NYB", "US Dollar (DXY)"),
    ("BTC-USD", "Bitcoin"),
]

# Human label for the session the ETFs reported, in priority order.
SESSION_NOTE = {
    "pre": "Premarket snapshot — index & sector ETFs are live pre-open prints.",
    "post": "After-hours snapshot — index & sector ETFs are live post-close prints.",
    "regular": "Regular session — market is open; quotes are live.",
    "closed": "Market closed — index & sector ETFs reflect the prior session's close.",
}


def _fmt_price(v: float) -> str:
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 100:
        return f"{v:,.1f}"
    if v >= 1:
        return f"{v:.2f}"
    return f"{v:.4f}"


def _fmt_pct(p) -> str:
    return "n/a" if p is None else f"{float(p):+.2f}%"


def _line(label: str, q: dict | None, *, prefix: str = "") -> str:
    if not q or q.get("price") is None:
        return f"- {label}: unavailable"
    return f"- {label}: {prefix}{_fmt_price(float(q['price']))} ({_fmt_pct(q.get('change_percent'))})"


def _event_line(ev: EconomicEvent, today: date) -> str:
    d = ev.event_date
    if d == today:
        day = "Today"
    elif d == today + timedelta(days=1):
        day = "Tomorrow"
    else:
        day = d.strftime("%a %b %-d")
    sym = ev.equity.symbol if ev.equity else None
    head = f"{sym} " if sym else ""
    time_str = ""
    if ev.event_time and not ev.all_day:
        time_str = " " + ev.event_time.strftime("%-I:%M%p").lower()
    flag = " (high)" if str(ev.importance).lower().endswith("high") else ""
    return f"- {day}: {head}{ev.title}{time_str}{flag}"


async def _events(session, today: date) -> list[EconomicEvent]:
    end = today + timedelta(days=EVENTS_AHEAD_DAYS)
    stmt = (
        select(EconomicEvent)
        .where(EconomicEvent.event_date >= today, EconomicEvent.event_date <= end)
        .order_by(EconomicEvent.event_date, EconomicEvent.event_time.nulls_last())
    )
    return list((await session.execute(stmt)).scalars().all())


async def _gather(provider, symbols: list[str]) -> dict:
    async def one(sym: str):
        try:
            return sym, await provider.get_extended_quote(sym)
        except Exception:
            return sym, None

    results = await asyncio.gather(*(one(s) for s in symbols))
    return dict(results)


async def main() -> int:
    all_symbols = [s for s, _ in INDICES + SECTORS + MACRO]
    today = datetime.now(ET).date()
    async with AsyncSessionLocal() as session:
        provider = await get_extended_quote_provider(session)
        try:
            data = await _gather(provider, all_symbols)
        finally:
            aclose = getattr(provider, "aclose", None)
            if aclose:
                try:
                    await aclose()
                except Exception:
                    pass
        try:
            events = await _events(session, today)
        except Exception:
            events = []

    # Pick the session label from the index ETFs (the headline instruments).
    sessions = [data[s]["session"] for s, _ in INDICES if data.get(s) and data[s].get("session")]
    session = next((x for x in ("pre", "post", "regular", "closed") if x in sessions), "closed")

    now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    out = [f"### SOURCE: markets (fetched {now_iso})", SESSION_NOTE[session]]

    out.append("Indices:")
    for sym, label in INDICES:
        out.append(_line(label, data.get(sym)))

    ranked = sorted(
        SECTORS,
        key=lambda t: (
            data.get(t[0]) is None,
            -(float(data[t[0]]["change_percent"]) if data.get(t[0]) and data[t[0]].get("change_percent") is not None else 0.0),
        ),
    )
    out.append("Sectors (best → worst):")
    for sym, label in ranked:
        q = data.get(sym)
        out.append(f"- {label}: {_fmt_pct(q.get('change_percent') if q else None)}")

    out.append("Macro backdrop:")
    for sym, label in MACRO:
        q = data.get(sym)
        if sym == "^TNX" and q and q.get("price") is not None:
            out.append(f"- {label}: {float(q['price']):.2f}% ({_fmt_pct(q.get('change_percent'))})")
        elif sym == "BTC-USD":
            out.append(_line(label, q, prefix="$"))
        else:
            out.append(_line(label, q))

    out.append(f"Events ahead (next {EVENTS_AHEAD_DAYS} days, from IC calendar):")
    if events:
        for ev in events:
            out.append(_event_line(ev, today))
    else:
        out.append("- none on the calendar")

    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
