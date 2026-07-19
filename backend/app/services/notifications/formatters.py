"""Plain-text formatters for Discord notification summaries."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional
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
    # Session the movers were measured in: 'pre' means genuine pre-market
    # data; anything else means the values are last regular-session closes
    # and the section must be labeled "AT CLOSE", not "PRE-MARKET".
    movers_session: str = "pre"
    # Alert stats
    active_alerts: int = 0
    triggered_overnight: int = 0
    # Pre-formatted "what needs a decision today" lines - shown first
    needs_attention: list[str] = field(default_factory=list)
    # News & Catalyst agent (T1 sub-PR 2/4): symbol -> catalyst line (<=80
    # chars), e.g. "DOE announced new uranium reserve program." None/empty
    # (the default) must render byte-identical to before this field existed -
    # see tests/test_services/test_briefing_formatters.py's catalyst-absent case.
    catalysts: Optional[dict[str, str]] = None
    # Section names that failed to assemble this run, from OUTSIDE the
    # formatter (e.g. the catalysts DB query in alerts.py's assembly step).
    # Seeds the same "Some data unavailable" footer the formatter's own
    # per-section try/except blocks feed - one source of truth for the
    # warning, regardless of where the failure happened.
    unavailable_sections: list[str] = field(default_factory=list)


def format_morning_pulse(data: MorningData) -> str:
    """Format the morning pulse notification as plain text."""
    # Seeded from assembly-side failures (e.g. the catalysts query) so they
    # feed the same footer as this function's own per-section try/excepts.
    # Default is [] - identical to the pre-existing `warnings: list[str] = []`.
    warnings: list[str] = list(data.unavailable_sections)
    sections: list[str] = []

    now_et = _get_et_now()
    header = f"☀️ Morning Pulse - {now_et.strftime('%b %d, %Y')}"
    sections.append(header)

    # -- Needs Attention (leads the briefing: decisions, not data) --
    try:
        if data.needs_attention:
            lines = ["⚡ NEEDS ATTENTION"]
            lines.extend(data.needs_attention[:8])
            sections.append("\n".join(lines))
    except Exception as e:
        warnings.append("needs attention")
        logger.warning(f"Error formatting needs attention: {e}")

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
    shown_mover_symbols: set[str] = set()
    try:
        if data.movers_session == "pre":
            header = "WATCHLIST PRE-MARKET MOVERS"
            empty_line = "No significant pre-market moves (>2%)"
        else:
            # No pre-market data (weekend, holiday, pre-open) - these are
            # last regular-session closes, so say so.
            header = "WATCHLIST MOVERS (AT CLOSE)"
            empty_line = "No significant moves (>2%) at last close"
        if data.premarket_movers:
            lines = [header]
            for m in data.premarket_movers[:5]:
                shown_mover_symbols.add(m["symbol"])
                arrow = "⬆️" if m["change_percent"] > 0 else "⬇️"
                line = f"{arrow} {m['symbol']} {_fmt_pct(m['change_percent'])}"
                catalyst = (data.catalysts or {}).get(m["symbol"])
                if catalyst:
                    line += f" — {catalyst}"
                lines.append(line)
            sections.append("\n".join(lines))
        else:
            sections.append(f"{header}\n{empty_line}")
    except Exception as e:
        warnings.append("pre-market movers")
        logger.warning(f"Error formatting pre-market movers: {e}")

    # -- Catalysts (News & Catalyst agent, non-mover watchlist news) --
    # Movers already got their catalyst inline above; this surfaces
    # high-relevance news for watchlist names that *didn't* move, so it
    # never repeats a symbol already shown. Absent/empty data.catalysts
    # (the default) adds no section - required for byte-identical output.
    try:
        if data.catalysts:
            extra = [
                (symbol, line)
                for symbol, line in data.catalysts.items()
                if symbol not in shown_mover_symbols
            ]
            if extra:
                lines = ["CATALYSTS"]
                for symbol, line in extra[:3]:
                    lines.append(f"• {symbol}: {line}")
                sections.append("\n".join(lines))
    except Exception as e:
        warnings.append("catalysts")
        logger.warning(f"Error formatting catalysts: {e}")

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
    # The alert's notes carry the pre-committed action ("trim VOO", "run the
    # checklist") - surfacing them attaches the decision to the trigger
    notes: Optional[str] = None


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
    # Post-market movers: [{symbol, change_percent}, ...] - only populated
    # when there is genuine post-session data, so the section never lies
    postmarket_movers: list[dict] = field(default_factory=list)
    # Alerts
    alerts_triggered: list[AlertTrigger] = field(default_factory=list)
    active_alerts: int = 0
    # Pre-formatted status lines for standing triggers near their thresholds
    approaching: list[str] = field(default_factory=list)
    # Pre-formatted playbook lines (triggers whose signal is hit/approaching)
    playbook_status: list[str] = field(default_factory=list)
    # Tomorrow's calendar: [{event_time, title, importance, event_type, symbol}, ...]
    tomorrow_events: list[dict] = field(default_factory=list)
    # News & Catalyst agent (T1 sub-PR 2/4's MorningData.catalysts, mirrored
    # for the EOD wrap in U11): symbol -> catalyst line (<=80 chars), e.g.
    # "DOE announced new uranium reserve program." None/empty (the default)
    # must render byte-identical to before this field existed - see
    # tests/test_services/test_briefing_formatters.py's catalyst-absent case.
    catalysts: Optional[dict[str, str]] = None
    # Section names that failed to assemble this run, from OUTSIDE the
    # formatter (e.g. the catalysts DB query in alerts.py's assembly step).
    # Seeds the same "Some data unavailable" footer the formatter's own
    # per-section try/except blocks feed - one source of truth for the
    # warning, regardless of where the failure happened.
    unavailable_sections: list[str] = field(default_factory=list)


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
    """Format the end-of-day wrap notification as plain text.

    Catalyst rendering rule: a symbol's catalyst text appears exactly once
    per wrap - suffixed onto its FIRST mover occurrence in render order
    (BIG MOVERS before POST-MARKET MOVERS; a symbol qualifying for both
    sections renders bare in the second), else listed in the standalone
    CATALYSTS section when the symbol appears in neither mover section.
    """
    # Seeded from assembly-side failures (e.g. the catalysts query) so they
    # feed the same footer as this function's own per-section try/excepts.
    # Default is [] - identical to the pre-existing `warnings: list[str] = []`.
    warnings: list[str] = list(data.unavailable_sections)
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
    # Tracks every symbol already printed by EOD's two mover sections (BIG
    # MOVERS + POST-MARKET MOVERS) - mirrors format_morning_pulse's
    # shown_mover_symbols, but spans both sections here since EOD has two.
    # Consulted INSIDE both mover loops (in render order) so a symbol
    # qualifying for both sections gets its catalyst suffixed at the first
    # occurrence only, and by the standalone CATALYSTS section below so it
    # never repeats a symbol already shown by either mover section.
    shown_mover_symbols: set[str] = set()

    def _mover_line(arrow: str, m: dict) -> str:
        """One mover line; catalyst suffix at the symbol's first occurrence."""
        line = f"{arrow} {m['symbol']} {_fmt_pct(m['change_percent'])}"
        if m["symbol"] not in shown_mover_symbols:
            catalyst = (data.catalysts or {}).get(m["symbol"])
            if catalyst:
                line += f" — {catalyst}"
        shown_mover_symbols.add(m["symbol"])
        return line

    try:
        big_up = [m for m in data.big_movers if m["change_percent"] > 3.0]
        big_down = [m for m in data.big_movers if m["change_percent"] < -3.0]

        if big_up or big_down:
            lines = ["BIG MOVERS (>3%)"]
            big_up.sort(key=lambda m: m["change_percent"], reverse=True)
            big_down.sort(key=lambda m: m["change_percent"])
            for m in big_up[:4]:
                lines.append(_mover_line("⬆️", m))
            for m in big_down[:4]:
                lines.append(_mover_line("⬇️", m))
            sections.append("\n".join(lines))
        else:
            sections.append("BIG MOVERS (>3%)\nNo moves >3% today")
    except Exception as e:
        warnings.append("big movers")
        logger.warning(f"Error formatting big movers: {e}")

    # -- Post-Market Movers --
    try:
        if data.postmarket_movers:
            lines = ["POST-MARKET MOVERS (>2%)"]
            for m in data.postmarket_movers[:5]:
                arrow = "⬆️" if m["change_percent"] > 0 else "⬇️"
                lines.append(_mover_line(arrow, m))
            sections.append("\n".join(lines))
    except Exception as e:
        warnings.append("post-market movers")
        logger.warning(f"Error formatting post-market movers: {e}")

    # -- Catalysts (News & Catalyst agent, non-mover watchlist news) --
    # Every mover symbol above already got its catalyst inline (at its first
    # occurrence); this surfaces high-relevance news for watchlist names
    # that *didn't* move (in either section), so it never repeats a symbol
    # already shown. Absent/empty data.catalysts (the default) adds no
    # section - required for byte-identical output. Placed immediately after
    # the mover sections, mirroring format_morning_pulse's CATALYSTS
    # adjacency to its one mover section.
    catalysts_section = ""
    try:
        if data.catalysts:
            extra = [
                (symbol, line)
                for symbol, line in data.catalysts.items()
                if symbol not in shown_mover_symbols
            ]
            if extra:
                lines = ["CATALYSTS"]
                for symbol, line in extra[:3]:
                    lines.append(f"• {symbol}: {line}")
                catalysts_section = "\n".join(lines)
    except Exception as e:
        warnings.append("catalysts")
        logger.warning(f"Error formatting catalysts: {e}")

    if catalysts_section:
        sections.append(catalysts_section)

    # -- Alerts --
    try:
        lines = ["ALERTS"]
        triggered_count = len(data.alerts_triggered)
        lines.append(
            f"🔔 {triggered_count} triggered today | {data.active_alerts} active"
        )
        for trigger in data.alerts_triggered[:5]:
            line = f"• {trigger.name}: Triggered at {_fmt_price(trigger.triggered_value)}"
            if trigger.notes:
                note = trigger.notes.strip().splitlines()[0]
                if len(note) > 110:
                    note = note[:107] + "..."
                line += f"\n  ↳ {note}"
            lines.append(line)
        if data.approaching:
            lines.append("Approaching:")
            lines.extend(data.approaching[:5])
        sections.append("\n".join(lines))
    except Exception as e:
        warnings.append("alerts")
        logger.warning(f"Error formatting alerts: {e}")

    # -- Trigger Playbook (standing decisions with live signal) --
    try:
        if data.playbook_status:
            lines = ["TRIGGER PLAYBOOK"]
            lines.extend(data.playbook_status[:5])
            sections.append("\n".join(lines))
    except Exception as e:
        warnings.append("playbook")
        logger.warning(f"Error formatting playbook: {e}")

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

    # Truncate if over Discord limit - drop tomorrow first, then catalysts,
    # then a hard char cut. CATALYSTS drops before the (higher-priority)
    # mover sections - i.e. right after TOMORROW in the ladder - so a rare
    # catalyst headline that pushes the message over the limit never costs
    # the core price/mover data ahead of it.
    if len(message) > DISCORD_CHAR_LIMIT and tomorrow_section:
        sections = [s for s in sections if s != tomorrow_section]
        message = "\n\n".join(sections)

    if len(message) > DISCORD_CHAR_LIMIT and catalysts_section:
        sections = [s for s in sections if s != catalysts_section]
        message = "\n\n".join(sections)

    if len(message) > DISCORD_CHAR_LIMIT:
        message = _truncate(message)

    return message


def _truncate(message: str) -> str:
    """Truncate message to fit Discord's character limit."""
    return message[: DISCORD_CHAR_LIMIT - 3] + "..."
