"""Tests for briefing v2 formatter additions (needs-attention, trigger notes)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.notifications import formatters as formatters_module
from app.services.notifications.formatters import (
    AlertTrigger,
    EODData,
    MorningData,
    ThemeData,
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


class TestEODWrapCatalysts:
    """News & Catalyst agent injection into the EOD wrap (U11, mirroring
    #210's TestMorningPulseCatalysts)."""

    _FIXED_NOW = datetime(2026, 7, 18, 16, 30, 0, tzinfo=ZoneInfo("America/New_York"))

    # Captured from this branch's pre-catalysts format_eod_wrap for the exact
    # EODData built below, with _get_et_now frozen to _FIXED_NOW - a real
    # byte-for-byte baseline, not a hand-computed guess (mirrors the morning
    # pulse golden's provenance).
    _GOLDEN_NO_CATALYSTS = (
        "🌙 End of Day Wrap - Jul 18, 2026\n\n"
        "MARKET CLOSE\nSPY +0.35%\nVIX 14.8\n\n"
        "THEME PERFORMANCE\n⚛️ Uranium & Nuclear: UUUU +2.10% | Strong day\n\n"
        "MY POSITIONS\nBest: CCJ +1.50% | VOO +0.20%\nWorst: VOO +0.20% | EQT -0.80%\n\n"
        "BIG MOVERS (>3%)\n⬆️ UUUU +5.20%\n\n"
        "POST-MARKET MOVERS (>2%)\n⬆️ CCJ +2.40%\n\n"
        "ALERTS\n🔔 1 triggered today | 35 active\n"
        "• CCJ < 105.00: Triggered at $95.03\n  ↳ Trim tier\n"
        "Approaching:\n• EQT half-starter zone: < $52 — -1.2% away\n\n"
        "TRIGGER PLAYBOOK\n• [HIT] Uranium thesis → add tier\n\n"
        "TOMORROW\n🔴 FOMC"
    )

    @staticmethod
    def _base_kwargs() -> dict:
        return dict(
            market={
                "SPY": {"price": 550.0, "change_percent": 0.35},
                "^VIX": {"price": 14.8, "change_percent": 0},
            },
            themes=[
                ThemeData(
                    name="Uranium & Nuclear",
                    emoji="⚛️",
                    positions=[{"symbol": "UUUU", "change_percent": 2.1}],
                )
            ],
            my_positions=[
                {"symbol": "CCJ", "change_percent": 1.5},
                {"symbol": "EQT", "change_percent": -0.8},
                {"symbol": "VOO", "change_percent": 0.2},
            ],
            big_movers=[{"symbol": "UUUU", "change_percent": 5.2}],
            postmarket_movers=[{"symbol": "CCJ", "change_percent": 2.4}],
            alerts_triggered=[
                AlertTrigger(name="CCJ < 105.00", triggered_value=95.03, notes="Trim tier")
            ],
            active_alerts=35,
            approaching=["• EQT half-starter zone: < $52 — -1.2% away"],
            playbook_status=["• [HIT] Uranium thesis → add tier"],
            tomorrow_events=[
                {"event_time": None, "title": "FOMC", "importance": "high", "event_type": "", "symbol": None}
            ],
        )

    def test_byte_identical_when_catalysts_and_unavailable_sections_absent(self, monkeypatch):
        """Leaving the new fields at their defaults (None / []) must render
        identically to the pre-existing formatter - the load-bearing
        inertness guarantee (per the adjudicated addendum: enforceable
        whenever the catalyst query returns nothing, which is what happens
        today in prod since the agents have never run)."""
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        data = EODData(**self._base_kwargs())  # catalysts/unavailable_sections default

        message = format_eod_wrap(data)

        assert message == self._GOLDEN_NO_CATALYSTS
        assert "CATALYSTS" not in message
        assert "Some data unavailable" not in message

    def test_catalyst_appended_to_big_mover_line(self, monkeypatch):
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["catalysts"] = {"UUUU": "DOE announced new uranium reserve program."}
        message = format_eod_wrap(EODData(**kwargs))

        assert (
            "⬆️ UUUU +5.20% — DOE announced new uranium reserve program." in message
        )
        # UUUU's catalyst is already inline in BIG MOVERS - must not also be
        # repeated in the standalone CATALYSTS section.
        assert "CATALYSTS" not in message

    def test_catalyst_appended_to_postmarket_mover_line(self, monkeypatch):
        """CCJ appears ONLY in POST-MARKET MOVERS (not BIG MOVERS) - its
        first (and only) mover occurrence is there, so that's where the
        catalyst suffix lands."""
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["catalysts"] = {"CCJ": "Uranium supply deal announced."}
        message = format_eod_wrap(EODData(**kwargs))

        assert "⬆️ CCJ +2.40% — Uranium supply deal announced." in message
        # CCJ's catalyst is already inline in POST-MARKET MOVERS - must not
        # also be repeated in the standalone CATALYSTS section.
        assert "CATALYSTS" not in message

    def test_symbol_in_both_mover_sections_suffixed_exactly_once(self, monkeypatch):
        """A symbol qualifying for BOTH mover sections (e.g. an earnings
        mover that keeps moving after hours) gets its catalyst at the FIRST
        occurrence only: suffixed in BIG MOVERS, bare in POST-MARKET MOVERS,
        absent from the standalone CATALYSTS section."""
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        catalyst_text = "DOE announced new uranium reserve program."
        kwargs = self._base_kwargs()
        # UUUU already leads BIG MOVERS (+5.20%); make it a post-market
        # mover too.
        kwargs["postmarket_movers"] = [
            {"symbol": "UUUU", "change_percent": 2.9},
            {"symbol": "CCJ", "change_percent": 2.4},
        ]
        kwargs["catalysts"] = {"UUUU": catalyst_text}
        message = format_eod_wrap(EODData(**kwargs))

        # Exactly one rendering of the catalyst text in the whole wrap.
        assert message.count(catalyst_text) == 1
        # Suffixed at the first occurrence (BIG MOVERS)...
        big_movers_section = message.split("BIG MOVERS (>3%)\n", 1)[1].split("\n\n", 1)[0]
        assert f"⬆️ UUUU +5.20% — {catalyst_text}" in big_movers_section
        # ...bare at the second (POST-MARKET MOVERS)...
        postmarket_section = message.split("POST-MARKET MOVERS (>2%)\n", 1)[1].split("\n\n", 1)[0]
        assert "⬆️ UUUU +2.90%" in postmarket_section
        assert catalyst_text not in postmarket_section
        # ...and never in the standalone section.
        assert "CATALYSTS" not in message

    def test_catalysts_section_for_non_mover_watchlist_symbols(self, monkeypatch):
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["catalysts"] = {"EQT": "New pipeline capacity approved."}
        message = format_eod_wrap(EODData(**kwargs))

        assert "CATALYSTS" in message
        assert "• EQT: New pipeline capacity approved." in message
        # Neither mover section is affected (no catalyst assigned to UUUU or
        # CCJ here) - isolate each and confirm nothing got appended.
        big_movers_section = message.split("BIG MOVERS (>3%)\n", 1)[1].split("\n\n", 1)[0]
        assert big_movers_section == "⬆️ UUUU +5.20%"
        postmarket_section = message.split("POST-MARKET MOVERS (>2%)\n", 1)[1].split("\n\n", 1)[0]
        assert postmarket_section == "⬆️ CCJ +2.40%"

    def test_catalysts_section_placed_after_movers_before_tomorrow(self, monkeypatch):
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["catalysts"] = {"EQT": "New pipeline capacity approved."}
        message = format_eod_wrap(EODData(**kwargs))

        assert (
            message.index("POST-MARKET MOVERS")
            < message.index("CATALYSTS")
            < message.index("TOMORROW")
        )

    def test_catalysts_section_capped_at_three_lines(self, monkeypatch):
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["catalysts"] = {f"SYM{i}": f"Catalyst {i}" for i in range(4)}
        message = format_eod_wrap(EODData(**kwargs))

        catalysts_block = message.split("CATALYSTS\n", 1)[1].split("\n\n", 1)[0]
        assert len(catalysts_block.strip().splitlines()) == 3

    def test_unavailable_sections_feeds_the_footer(self, monkeypatch):
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["unavailable_sections"] = ["catalysts"]
        message = format_eod_wrap(EODData(**kwargs))

        assert "⚠️ Some data unavailable" in message

    def test_successful_empty_catalysts_no_warning_no_section(self, monkeypatch):
        """A query that legitimately returns nothing (slow news day, or the
        agent has never run) must not trip the footer warning - only an
        assembly-side FAILURE (unavailable_sections) does that."""
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["catalysts"] = {}
        message = format_eod_wrap(EODData(**kwargs))

        assert "CATALYSTS" not in message
        assert "Some data unavailable" not in message

    def test_truncation_drops_catalysts_before_mover_sections(self, monkeypatch):
        """When dropping TOMORROW alone isn't enough (catalyst text is
        long), CATALYSTS drops next - core price/mover data survives before
        the catalysts extra. (Base message here is 479 chars; the 3 catalyst
        lines alone add ~1830 chars, comfortably over the 2000 limit even
        with TOMORROW already gone, so the ladder must reach CATALYSTS.)"""
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["catalysts"] = {
            "EQT": "x" * 600,
            "VOO": "y" * 600,
            "SPY": "z" * 600,
        }

        message = format_eod_wrap(EODData(**kwargs))

        assert len(message) <= 2000
        assert "TOMORROW" not in message
        assert "CATALYSTS" not in message
        # The higher-priority sections ahead of CATALYSTS in the ladder
        # survive intact.
        assert "BIG MOVERS (>3%)" in message
        assert "POST-MARKET MOVERS (>2%)" in message
        assert "MARKET CLOSE" in message

    def test_truncation_drops_tomorrow_only_when_that_alone_suffices(self, monkeypatch):
        """The ladder stops as soon as the message fits - a bulky TOMORROW
        with a short CATALYSTS must not drop CATALYSTS unnecessarily."""
        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        kwargs = self._base_kwargs()
        kwargs["catalysts"] = {"EQT": "New pipeline capacity approved with strong upside."}
        kwargs["tomorrow_events"] = [
            {
                "event_time": None,
                "title": "FOMC " + "a" * 1500,
                "importance": "high",
                "event_type": "",
                "symbol": None,
            }
        ]

        message = format_eod_wrap(EODData(**kwargs))

        assert len(message) <= 2000
        assert "TOMORROW" not in message
        assert "CATALYSTS" in message
        assert "New pipeline capacity approved" in message

    def test_mention_neutralization_preserved_through_eod_formatter(self, monkeypatch):
        """Formatter-level check that pre-neutralized catalyst text (as
        get_catalyst_lines always returns - see test_catalysts.py, and the
        assembly-level test in test_tasks/test_alerts_eod_catalysts.py for
        the DB-backed path) passes through the EOD formatter unchanged - the
        formatter must not need its own sanitization."""
        from app.services.catalysts import _neutralize_mentions

        monkeypatch.setattr(formatters_module, "_get_et_now", lambda: self._FIXED_NOW)

        neutralized = _neutralize_mentions("Ping the desk @everyone about this.")
        assert "@everyone" not in neutralized  # sanity: fixture is actually defanged

        kwargs = self._base_kwargs()
        kwargs["catalysts"] = {"EQT": neutralized}
        message = format_eod_wrap(EODData(**kwargs))

        assert "@everyone" not in message
        assert neutralized in message
