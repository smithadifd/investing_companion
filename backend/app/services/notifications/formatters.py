"""Plain-text formatters for Discord notification summaries."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, time
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

DISCORD_CHAR_LIMIT = 2000
ET = ZoneInfo("America/New_York")

# Theme emoji mapping - substring match against watchlist name (case-insensitive)
THEME_EMOJI_MAP = {
    "uranium": "⚛️",
    "nuclear": "⚛️",
    "mineral": "🪨",
    "ree": "🪨",
    "critical": "🪨",
    "precious": "🥇",
    "gold": "🥇",
    "silver": "🥇",
    "fiscal": "💵",
    "dominance": "💵",
}


def get_theme_emoji(watchlist_name: str) -> str:
    """Get emoji for a watchlist based on its name."""
    name_lower = watchlist_name.lower()
    for keyword, emoji in THEME_EMOJI_MAP.items():
        if keyword in name_lower:
            return emoji
    return "📊"


def _fmt_pct(value: float) -> str:
    """Format percentage with sign: +0.42% or -1.30%."""
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _fmt_price(value: float) -> str:
    """Format price for display."""
    if value >= 1000:
        return f"${value:,.0f}"
    elif value >= 1:
        return f"${value:.2f}"
    else:
        return f"${value:.4f}"


def _color(change_pct: float) -> str:
    """Color emoji based on change magnitude."""
    if change_pct > 0.5:
        return "🟢"
    elif change_pct < -0.5:
        return "🔴"
    return "🟡"


def _get_et_now() -> datetime:
    """Get current time in Eastern timezone."""
    return datetime.now(ET)


# ---------------------------------------------------------------------------
# Morning Pulse
# ---------------------------------------------------------------------------

@dataclass
class MorningData:
    """Data container for morning pulse notification."""
    # Futures: symbol -> {price, change_percent}
    futures: dict[str, dict] = field(default_factory=dict)
    # VIX: {price, change}
    vix: dict = field(default_factory=dict)
    # 10Y: {price, change}
    ten_year: dict = field(default_factory=dict)
    # Overnight moves: [{name, symbol, change_percent, price}, ...]
    overnight_moves: list[dict] = field(default_factory=list)
    # Calendar events: [{event_time, title, importance, event_type, symbol}, ...]
    calendar_events: list[dict] = field(default_factory=list)
    # Pre-market movers: [{symbol, change_percent}, ...]
    premarket_movers: list[dict] = field(default_factory=list)
    # Alert stats
    active_alerts: int = 0
    triggered_overnight: int = 0


def format_morning_pulse(data: MorningData) -> str:
    """Format the morning pulse notification as plain text."""
    warnings: list[str] = []
    sections: list[str] = []

    now_et = _get_et_now()
    header = f"☀️ Morning Pulse - {now_et.strftime('%b %d, %Y')}"
    sections.append(header)

    # -- Futures & Pre-Market --
    try:
        if data.futures or data.vix or data.ten_year:
            lines = ["FUTURES & PRE-MARKET"]
            # Futures line
            parts = []
            for sym, label in [("ES=F", "ES"), ("NQ=F", "NQ"), ("RTY=F", "RTY")]:
                info = data.futures.get(sym)
                if info:
                    parts.append(f"{label} {_fmt_pct(info['change_percent'])}")
            if parts:
                lines.append(" | ".join(parts))

            # VIX + 10Y line
            indicator_parts = []
            if data.vix:
                vix_price = data.vix.get("price", 0)
                vix_chg = data.vix.get("change", 0)
                sign = "+" if vix_chg > 0 else ""
                indicator_parts.append(f"VIX {vix_price:.1f} ({sign}{vix_chg:.1f})")
            if data.ten_year:
                ty_price = data.ten_year.get("price", 0)
                ty_chg = data.ten_year.get("change", 0)
                bp = ty_chg * 100  # yield change to basis points
                sign = "+" if bp > 0 else ""
                indicator_parts.append(f"10Y {ty_price:.2f}% ({sign}{bp:.0f}bp)")
            if indicator_parts:
                lines.append(" | ".join(indicator_parts))

            sections.append("\n".join(lines))
    except Exception as e:
        warnings.append("futures")
        logger.warning(f"Error formatting futures: {e}")

    # -- Overnight Moves --
    try:
        if data.overnight_moves:
            lines = ["OVERNIGHT MOVES"]
            # Group: metals, dollar, energy, international
            metals = []
            dollar = []
            energy = []
            intl = []
            for m in data.overnight_moves:
                name_lower = m["name"].lower()
                if "gold" in name_lower or "silver" in name_lower:
                    metals.append(m)
                elif "dollar" in name_lower or "dxy" in name_lower:
                    dollar.append(m)
                elif any(w in name_lower for w in ["crude", "oil", "nat gas", "gas"]):
                    energy.append(m)
                else:
                    intl.append(m)

            # Metals line
            if metals:
                parts = []
                for m in metals:
                    parts.append(
                        f"{m['name']} {_fmt_pct(m['change_percent'])} ({_fmt_price(m['price'])})"
                    )
                c = _color(metals[0]["change_percent"])
                lines.append(f"{c} {' | '.join(parts)}")

            # Dollar line
            if dollar:
                d = dollar[0]
                c = _color(d["change_percent"])
                lines.append(
                    f"{c} {d['name']} {_fmt_pct(d['change_percent'])} ({d['price']:.1f})"
                )

            # Energy line
            if energy:
                parts = []
                for m in energy:
                    if abs(m["change_percent"]) < 0.1:
                        parts.append(f"{m['name']} flat ({_fmt_price(m['price'])})")
                    else:
                        parts.append(
                            f"{m['name']} {_fmt_pct(m['change_percent'])}"
                        )
                c = _color(energy[0]["change_percent"]) if energy else "🟡"
                lines.append(f"{c} {' | '.join(parts)}")

            # International line
            if intl:
                parts = [
                    f"{m['name']} {_fmt_pct(m['change_percent'])}" for m in intl
                ]
                lines.append(f"🌏 {' | '.join(parts)}")

            sections.append("\n".join(lines))
    except Exception as e:
        warnings.append("overnight moves")
        logger.warning(f"Error formatting overnight moves: {e}")

    # -- Today's Calendar --
    try:
        lines = ["TODAY'S CALENDAR"]
        if data.calendar_events:
            for evt in data.calendar_events[:6]:
                importance = evt.get("importance", "medium")
                evt_type = evt.get("event_type", "")
                symbol = evt.get("symbol")

                if evt_type == "earnings" or evt_type == "ex_dividend":
                    icon = "📊"
                elif importance == "high":
                    icon = "🔴"
                else:
                    icon = "🟡"

                time_str = ""
                if evt.get("event_time"):
                    t = evt["event_time"]
                    if isinstance(t, time):
                        time_str = t.strftime("%-I:%M %p")
                    elif isinstance(t, str) and t.strip():
                        time_str = t.strip()

                title = evt.get("title", "Event")
                if symbol:
                    title = f"**{symbol}**: {title}"

                if time_str:
                    lines.append(f"{icon} {time_str} - {title}")
                else:
                    lines.append(f"{icon} {title}")
        else:
            lines.append("No major events scheduled")
        sections.append("\n".join(lines))
    except Exception as e:
        warnings.append("calendar")
        logger.warning(f"Error formatting calendar: {e}")

    # -- Watchlist Pre-Market Movers --
    try:
        if data.premarket_movers:
            lines = ["WATCHLIST PRE-MARKET MOVERS"]
            for m in data.premarket_movers[:5]:
                arrow = "⬆️" if m["change_percent"] > 0 else "⬇️"
                lines.append(f"{arrow} {m['symbol']} {_fmt_pct(m['change_percent'])}")
            sections.append("\n".join(lines))
        else:
            sections.append("WATCHLIST PRE-MARKET MOVERS\nNo significant pre-market moves (>2%)")
    except Exception as e:
        warnings.append("pre-market movers")
        logger.warning(f"Error formatting pre-market movers: {e}")

    # -- Alert Status --
    sections.append(
        f"ACTIVE ALERTS: {data.active_alerts} | TRIGGERED OVERNIGHT: {data.triggered_overnight}"
    )

    # -- Footer warning --
    if warnings:
        sections.append("⚠️ Some data unavailable")

    message = "\n\n".join(sections)
    if len(message) > DISCORD_CHAR_LIMIT:
        message = _truncate(message)
    return message


# ---------------------------------------------------------------------------
# End of Day Wrap
# ---------------------------------------------------------------------------

@dataclass
class ThemeData:
    """Performance data for a single watchlist theme."""
    name: str = ""
    emoji: str = "📊"
    # All positions with quotes: [{symbol, change_percent}, ...]
    positions: list[dict] = field(default_factory=list)


@dataclass
class AlertTrigger:
    """A single alert trigger event."""
    name: str = ""
    triggered_value: float = 0.0


@dataclass
class EODData:
    """Data container for end-of-day wrap notification."""
    # Market close: {symbol: {price, change_percent}}
    market: dict[str, dict] = field(default_factory=dict)
    # Themes (non-default watchlists)
    themes: list[ThemeData] = field(default_factory=list)
    # My positions (default watchlist): [{symbol, change_percent}, ...]
    my_positions: list[dict] = field(default_factory=list)
    # Big movers across all watchlists: [{symbol, change_percent}, ...]
    big_movers: list[dict] = field(default_factory=list)
    # Alerts
    alerts_triggered: list[AlertTrigger] = field(default_factory=list)
    active_alerts: int = 0
    # Tomorrow's calendar: [{event_time, title, importance, event_type, symbol}, ...]
    tomorrow_events: list[dict] = field(default_factory=list)


def _theme_narrative(positions: list[dict]) -> str:
    """Generate a brief narrative for theme performance."""
    if not positions:
        return "No data"
    avg = sum(p["change_percent"] for p in positions) / len(positions)
    if avg > 1.0:
        return "Strong day"
    elif avg < -1.0:
        return "Weak day"
    else:
        # Show top movers
        notable = sorted(positions, key=lambda p: abs(p["change_percent"]), reverse=True)
        parts = [
            f"{p['symbol']} {_fmt_pct(p['change_percent'])}"
            for p in notable[:3]
        ]
        return ", ".join(parts)


def format_eod_wrap(data: EODData) -> str:
    """Format the end-of-day wrap notification as plain text."""
    warnings: list[str] = []
    sections: list[str] = []

    now_et = _get_et_now()
    header = f"🌙 End of Day Wrap - {now_et.strftime('%b %d, %Y')}"
    sections.append(header)

    # -- Market Close --
    try:
        lines = ["MARKET CLOSE"]
        spy = data.market.get("SPY", {})
        qqq = data.market.get("QQQ", {})
        iwm = data.market.get("IWM", {})
        parts = []
        if spy:
            parts.append(f"SPY {_fmt_pct(spy.get('change_percent', 0))}")
        if qqq:
            parts.append(f"QQQ {_fmt_pct(qqq.get('change_percent', 0))}")
        if iwm:
            parts.append(f"IWM {_fmt_pct(iwm.get('change_percent', 0))}")
        if parts:
            lines.append(" | ".join(parts))

        indicator_parts = []
        vix = data.market.get("^VIX", {})
        ty = data.market.get("^TNX", {})
        dxy = data.market.get("DX-Y.NYB", {})
        if vix:
            indicator_parts.append(f"VIX {vix.get('price', 0):.1f}")
        if ty:
            indicator_parts.append(f"10Y {ty.get('price', 0):.2f}%")
        if dxy:
            indicator_parts.append(f"DXY {dxy.get('price', 0):.1f}")
        if indicator_parts:
            lines.append(" | ".join(indicator_parts))

        sections.append("\n".join(lines))
    except Exception as e:
        warnings.append("market close")
        logger.warning(f"Error formatting market close: {e}")

    # -- Theme Performance --
    try:
        if data.themes:
            lines = ["THEME PERFORMANCE"]
            for theme in data.themes:
                if not theme.positions:
                    continue
                # Use first position as benchmark headline
                benchmark = theme.positions[0]
                headline = (
                    f"{benchmark['symbol']} {_fmt_pct(benchmark['change_percent'])}"
                )
                narrative = _theme_narrative(theme.positions)
                lines.append(
                    f"{theme.emoji} {theme.name}: {headline} | {narrative}"
                )
            if len(lines) > 1:
                sections.append("\n".join(lines))
    except Exception as e:
        warnings.append("theme performance")
        logger.warning(f"Error formatting themes: {e}")

    # -- My Positions --
    try:
        if data.my_positions:
            lines = ["MY POSITIONS"]
            sorted_pos = sorted(
                data.my_positions, key=lambda p: p["change_percent"], reverse=True
            )
            best = sorted_pos[:2]
            worst = sorted_pos[-2:]

            best_parts = [
                f"{p['symbol']} {_fmt_pct(p['change_percent'])}" for p in best
            ]
            lines.append(f"Best: {' | '.join(best_parts)}")

            # Only show worst if different from best (>2 positions)
            if len(sorted_pos) > 2:
                worst_parts = [
                    f"{p['symbol']} {_fmt_pct(p['change_percent'])}" for p in worst
                ]
                lines.append(f"Worst: {' | '.join(worst_parts)}")

            sections.append("\n".join(lines))
    except Exception as e:
        warnings.append("positions")
        logger.warning(f"Error formatting positions: {e}")

    # -- Big Movers --
    try:
        big_up = [m for m in data.big_movers if m["change_percent"] > 3.0]
        big_down = [m for m in data.big_movers if m["change_percent"] < -3.0]

        if big_up or big_down:
            lines = ["BIG MOVERS (>3%)"]
            big_up.sort(key=lambda m: m["change_percent"], reverse=True)
            big_down.sort(key=lambda m: m["change_percent"])
            for m in big_up[:4]:
                lines.append(f"⬆️ {m['symbol']} {_fmt_pct(m['change_percent'])}")
            for m in big_down[:4]:
                lines.append(f"⬇️ {m['symbol']} {_fmt_pct(m['change_percent'])}")
            sections.append("\n".join(lines))
        else:
            sections.append("BIG MOVERS (>3%)\nNo moves >3% today")
    except Exception as e:
        warnings.append("big movers")
        logger.warning(f"Error formatting big movers: {e}")

    # -- Alerts --
    try:
        lines = ["ALERTS"]
        triggered_count = len(data.alerts_triggered)
        lines.append(
            f"🔔 {triggered_count} triggered today | {data.active_alerts} active"
        )
        for trigger in data.alerts_triggered[:5]:
            lines.append(
                f"• {trigger.name}: Triggered at {_fmt_price(trigger.triggered_value)}"
            )
        sections.append("\n".join(lines))
    except Exception as e:
        warnings.append("alerts")
        logger.warning(f"Error formatting alerts: {e}")

    # -- Tomorrow's Calendar --
    tomorrow_section = ""
    try:
        if data.tomorrow_events:
            lines = ["TOMORROW"]
            for evt in data.tomorrow_events[:5]:
                importance = evt.get("importance", "medium")
                evt_type = evt.get("event_type", "")
                if evt_type in ("earnings", "ex_dividend"):
                    icon = "📊"
                elif importance == "high":
                    icon = "🔴"
                else:
                    icon = "🟡"

                time_str = ""
                if evt.get("event_time"):
                    t = evt["event_time"]
                    if isinstance(t, time):
                        time_str = t.strftime("%-I:%M %p")
                    elif isinstance(t, str) and t.strip():
                        time_str = t.strip()

                title = evt.get("title", "Event")
                if time_str:
                    lines.append(f"{icon} {time_str} - {title}")
                else:
                    lines.append(f"{icon} {title}")
            tomorrow_section = "\n".join(lines)
    except Exception as e:
        warnings.append("tomorrow")
        logger.warning(f"Error formatting tomorrow: {e}")

    if tomorrow_section:
        sections.append(tomorrow_section)

    # -- Footer warning --
    if warnings:
        sections.append("⚠️ Some data unavailable")

    message = "\n\n".join(sections)

    # Truncate if over Discord limit - drop tomorrow first, then big movers
    if len(message) > DISCORD_CHAR_LIMIT and tomorrow_section:
        sections = [s for s in sections if s != tomorrow_section]
        message = "\n\n".join(sections)

    if len(message) > DISCORD_CHAR_LIMIT:
        message = _truncate(message)

    return message


def _truncate(message: str) -> str:
    """Truncate message to fit Discord's character limit."""
    return message[: DISCORD_CHAR_LIMIT - 3] + "..."
