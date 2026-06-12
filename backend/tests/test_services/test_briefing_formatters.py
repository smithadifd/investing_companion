"""Tests for briefing v2 formatter additions (needs-attention, trigger notes)."""

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
