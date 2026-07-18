"""Tests for briefing v2 formatter additions (needs-attention, trigger notes)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.notifications import formatters as formatters_module
from app.services.notifications.formatters import (
    AlertTrigger,
    EODData,
    MorningData,
    format_eod_wrap,
    format_morning_pulse,
)


class TestMorningPulseNeedsAttention:
    def test_needs_attention_leads_the_briefing(self):
        data = MorningData(
            needs_attention=[
                "⚠️ EQT half-starter zone: < $52 — -1.2% away (last 52.61)",
                "🎯 CCJ within 4.0% of target $105 (Uranium & Nuclear)",
            ],
            active_alerts=35,
        )

        message = format_morning_pulse(data)

        assert "⚡ NEEDS ATTENTION" in message
        # The section comes before the alert-count footer
        assert message.index("NEEDS ATTENTION") < message.index("ACTIVE ALERTS")
        assert "EQT half-starter" in message
        assert "CCJ within 4.0%" in message

    def test_no_section_when_nothing_needs_attention(self):
        message = format_morning_pulse(MorningData(active_alerts=10))
        assert "NEEDS ATTENTION" not in message

    def test_caps_at_eight_items(self):
        data = MorningData(needs_attention=[f"item {i}" for i in range(12)])
        message = format_morning_pulse(data)
        assert "item 7" in message
        assert "item 8" not in message


class TestEODWrapDecisions:
    def test_trigger_notes_attach_the_action(self):
        data = EODData(
            alerts_triggered=[
                AlertTrigger(
                    name="CCJ < 105.00",
                    triggered_value=95.03,
                    notes="First add tier $100-105. Run the six-point checklist.",
                )
            ],
            active_alerts=35,
        )

        message = format_eod_wrap(data)

        assert "CCJ < 105.00" in message
        assert "↳ First add tier" in message

    def test_long_notes_truncated_to_first_line(self):
        data = EODData(
            alerts_triggered=[
                AlertTrigger(
                    name="X > 1.00",
                    triggered_value=2.0,
                    notes="line one " + "x" * 200 + "\nline two should not appear",
                )
            ],
        )

        message = format_eod_wrap(data)

        assert "line two" not in message
        assert "..." in message

    def test_approaching_section(self):
        data = EODData(
            approaching=["• EQT half-starter zone: < $52 — -1.2% away"],
            active_alerts=35,
        )

        message = format_eod_wrap(data)

        assert "Approaching:" in message
        assert "EQT half-starter" in message


class TestMorningPulseMoversLabel:
    def test_pre_session_keeps_premarket_header(self):
        data = MorningData(
            premarket_movers=[{"symbol": "EQT", "change_percent": 3.2}],
            movers_session="pre",
        )

        message = format_morning_pulse(data)

        assert "WATCHLIST PRE-MARKET MOVERS" in message
        assert "EQT +3.20%" in message
        assert "AT CLOSE" not in message

    def test_closed_session_labeled_at_close_not_premarket(self):
        """Weekend/holiday fallback shows last closes - never calls them
        pre-market moves (the original mislabel bug)."""
        data = MorningData(
            premarket_movers=[{"symbol": "EQT", "change_percent": -2.8}],
            movers_session="closed",
        )

        message = format_morning_pulse(data)

        assert "WATCHLIST MOVERS (AT CLOSE)" in message
        assert "PRE-MARKET MOVERS" not in message
        assert "EQT -2.80%" in message

    def test_empty_movers_honest_in_both_sessions(self):
        pre = format_morning_pulse(MorningData(movers_session="pre"))
        assert "No significant pre-market moves (>2%)" in pre

        closed = format_morning_pulse(MorningData(movers_session="closed"))
        assert "No significant moves (>2%) at last close" in closed
        assert "PRE-MARKET" not in closed


class TestMorningPulseCatalysts:
    """News & Catalyst agent injection into the morning pulse (T1 sub-PR 2/4)."""

    _FIXED_NOW = datetime(2026, 7, 18, 8, 0, 0, tzinfo=ZoneInfo("America/New_York"))

    # Captured from origin/main's format_morning_pulse (pre-catalysts) for the
    # exact MorningData built below, with _get_et_now frozen to _FIXED_NOW -
    # a real byte-for-byte baseline, not a hand-computed guess.
    _GOLDEN_NO_CATALYSTS = (
        "☀️ Morning Pulse - Jul 18, 2026\n\n"
        "⚡ NEEDS ATTENTION\n⚠️ example needs-attention line\n\n"
        "FUTURES & PRE-MARKET\nES +0.42%\nVIX 14.2 (-0.3) | 10Y 4.31% (+2bp)\n\n"
        "OVERNIGHT MOVES\n🟢 Gold +1.10% ($2,400)\n\n"
        "TODAY'S CALENDAR\n🔴 CPI\n\n"
        "WATCHLIST PRE-MARKET MOVERS\n⬆️ UUUU +5.10%\n\n"
        "ACTIVE ALERTS: 12 | TRIGGERED OVERNIGHT: 2"
    )

    @staticmethod
    def _base_kwargs() -> dict:
        return dict(
            futures={"ES=F": {"price": 5000.0, "change_percent": 0.42}},
            vix={"price": 14.2, "change": -0.3},
            ten_year={"price": 4.31, "change": 0.02},
            overnight_moves=[
                {"name": "Gold", "symbol": "GC=F", "change_percent": 1.1, "price": 2400.0}
            ],
            calendar_events=[
                {"event_time": None, "title": "CPI", "importance": "high", "event_type": "", "symbol": None}
            ],
            premarket_movers=[{"symbol": "UUUU", "change_percent": 5.1}],
            movers_session="pre",
            active_alerts=12,
            triggered_overnight=2,
            needs_attention=["⚠️ example needs-attention line"],
        )

    def test_byte_identical_when_catalysts_and_unavailable_sections_absent(self, monkeypatch):
        """Leaving the new fields at their defaults (None / []) must render
        identically to the pre-existing formatter - the explicit test the
        design contract calls for."""
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        data = MorningData(**self._base_kwargs())  # catalysts/unavailable_sections default

        message = format_morning_pulse(data)

        assert message == self._GOLDEN_NO_CATALYSTS
        assert "CATALYSTS" not in message
        assert "Some data unavailable" not in message

    def test_catalyst_appended_to_mover_line(self, monkeypatch):
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["catalysts"] = {"UUUU": "DOE announced new uranium reserve program."}
        message = format_morning_pulse(MorningData(**kwargs))

        assert (
            "⬆️ UUUU +5.10% — DOE announced new uranium reserve program." in message
        )
        # The mover already carries its catalyst inline - it must not also be
        # repeated in the standalone CATALYSTS section.
        assert "CATALYSTS" not in message

    def test_catalysts_section_for_non_mover_watchlist_symbols(self, monkeypatch):
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["catalysts"] = {"EQT": "New pipeline capacity approved."}
        message = format_morning_pulse(MorningData(**kwargs))

        assert "CATALYSTS" in message
        assert "• EQT: New pipeline capacity approved." in message
        # UUUU's mover line is unaffected (no catalyst assigned to it here) -
        # isolate the movers section and confirm nothing got appended to it.
        movers_section = message.split("WATCHLIST PRE-MARKET MOVERS\n", 1)[1].split("\n\n", 1)[0]
        assert movers_section == "⬆️ UUUU +5.10%"

    def test_catalysts_section_capped_at_three_lines(self, monkeypatch):
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["catalysts"] = {f"SYM{i}": f"Catalyst {i}" for i in range(5)}
        message = format_morning_pulse(MorningData(**kwargs))

        catalysts_block = message.split("CATALYSTS\n", 1)[1].split("\n\n", 1)[0]
        assert len(catalysts_block.strip().splitlines()) == 3

    def test_unavailable_sections_feeds_the_footer(self, monkeypatch):
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["unavailable_sections"] = ["catalysts"]
        message = format_morning_pulse(MorningData(**kwargs))

        assert "⚠️ Some data unavailable" in message


class TestEODPostMarketMovers:
    def test_postmarket_section_rendered(self):
        data = EODData(
            postmarket_movers=[
                {"symbol": "EQT", "change_percent": -6.0},
                {"symbol": "CCJ", "change_percent": 2.4},
            ],
        )

        message = format_eod_wrap(data)

        assert "POST-MARKET MOVERS (>2%)" in message
        assert "⬇️ EQT -6.00%" in message
        assert "⬆️ CCJ +2.40%" in message

    def test_no_section_when_no_postmarket_data(self):
        message = format_eod_wrap(EODData())
        assert "POST-MARKET" not in message
