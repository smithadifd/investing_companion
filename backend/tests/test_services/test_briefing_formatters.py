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
