"""BZ14 — same-cycle alert batching + equity deep links.

Two seams are pinned here, one section each.

**Seam 2 (declared second, tested first — it is the leaf):** the
*delivery-payload -> embed-line* seam, located at
``DiscordNotificationService.send_alert_batch`` / ``send_alert_notification``.
Its interface: a list of outbox payload dicts in, exactly ONE webhook POST out,
whose single embed's description carries one ``• **[SYM](FRONTEND_URL/equity/
SYM)** …`` line per alert, in the order given. Observed through the existing
``_post_webhook`` choke point via the captured-payload adapter already used by
``test_discord_allowed_mentions.py`` (``_mock_client`` / ``_sent_payload``) —
no test here reaches past the interface into the builder.

**Seam 1:** the *outbox-drain -> Discord-send* seam, located where
``AlertService.deliver_pending`` calls into ``discord_service``. Before BZ14 its
interface was "one claimed row => one ``send_alert_notification`` await". After
BZ14 it is "one claimed GROUP of same-cycle rows => ONE await" —
``send_alert_notification`` for a lone row (the rich single-alert embed is
unchanged), ``send_alert_batch`` for two or more. Observed through the
pre-existing ``@patch("app.services.alert.discord_service")`` mock adapter.

Expected embed shapes in the Seam 2 section are hand-authored literals, not
re-derived from the builder.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.services.alert as alertmod
from app.core.config import settings
from app.db.models.alert import AlertDeliveryStatus
from app.services.notifications.discord import DiscordNotificationService

from tests.factories import create_test_alert, create_test_equity
from tests.test_services.test_alert_outbox import (
    _deliveries,
    _make_triggered_alert,
    _mock_quote,
)

WEBHOOK_URL = "https://discord.com/api/webhooks/123456789/test-token"
FRONTEND = "https://ic.example.test"


# ===========================================================================
# Seam 2 — delivery-payload -> embed-line
# ===========================================================================


@pytest.fixture(autouse=True)
def _forbid_real_client(monkeypatch):
    """Guard: no test in this module may construct a network-capable client.

    Same guard as test_discord_allowed_mentions.py — every notifier under test
    gets a mock client injected first, so reaching the real-construction branch
    means the injection silently failed and a live POST was about to happen.
    """

    def _boom(*args, **kwargs):
        raise AssertionError(
            "real httpx.AsyncClient must never be constructed in "
            "test_alert_batching.py - a mock client should always be injected"
        )

    monkeypatch.setattr(httpx, "AsyncClient", _boom)


@pytest.fixture(autouse=True)
def _frontend_url(monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_URL", FRONTEND)


def _mock_client(status_code: int = 204) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = ""
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    return client


def _notifier(client: MagicMock) -> DiscordNotificationService:
    notifier = DiscordNotificationService(webhook_url=WEBHOOK_URL)
    notifier._client = client
    return notifier


def _sent_payload(client: MagicMock) -> dict:
    _, kwargs = client.post.call_args
    return kwargs["json"]


def _payload(
    symbol: str,
    *,
    alert_name: str,
    condition_type: str = "above",
    threshold: str = "100",
    current: str = "105",
    is_ratio: bool = False,
    name: str | None = None,
    notes: str | None = None,
    comparison_period: str | None = None,
    condition_override: str | None = None,
) -> dict:
    """One outbox payload, exactly as ``_build_delivery_payload`` snapshots it
    (Decimals already stringified — the batch sender must accept that)."""
    return {
        "alert_name": alert_name,
        "target_symbol": symbol,
        "target_name": name or f"{symbol} Inc.",
        "condition_type": condition_type,
        "threshold_value": threshold,
        "current_value": current,
        "comparison_period": comparison_period,
        "is_ratio": is_ratio,
        "notes": notes,
        "condition_override": condition_override,
    }


class TestBatchEmbedShape:
    """N payloads in -> exactly one POST carrying one embed with N lines."""

    async def test_three_alerts_produce_one_post_with_three_deep_linked_lines(self):
        client = _mock_client()
        notifier = _notifier(client)

        ok, err = await notifier.send_alert_batch(
            [
                _payload(
                    "AAPL",
                    alert_name="AAPL breakout",
                    condition_type="crosses_above",
                    threshold="200",
                    current="205",
                ),
                _payload(
                    "MSFT",
                    alert_name="MSFT dip",
                    condition_type="below",
                    threshold="400",
                    current="392.5",
                ),
                _payload(
                    "NVDA",
                    alert_name="NVDA stop",
                    condition_type="percent_down",
                    threshold="7",
                    current="812",
                    comparison_period="1d",
                ),
            ]
        )

        assert (ok, err) == (True, None)
        client.post.assert_awaited_once()  # ONE message for the whole cycle

        payload = _sent_payload(client)
        assert len(payload["embeds"]) == 1
        embed = payload["embeds"][0]

        # Hand-authored known-good shape (not re-derived from the builder).
        assert embed["title"] == "🔔 3 Alerts Triggered"
        assert embed["description"] == "\n".join(
            [
                "• **[AAPL](https://ic.example.test/equity/AAPL)** — "
                "AAPL breakout: crossed above $200.00 (now $205.00)",
                "• **[MSFT](https://ic.example.test/equity/MSFT)** — "
                "MSFT dip: below $400.00 (now $392.50)",
                "• **[NVDA](https://ic.example.test/equity/NVDA)** — "
                "NVDA stop: down 7% in 1d (now $812.00)",
            ]
        )
        assert embed["footer"] == {"text": "Investing Companion"}

    async def test_line_order_follows_input_order(self):
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch(
            [
                _payload("ZZZZ", alert_name="last-in-alphabet, first-in"),
                _payload("AAAA", alert_name="first-in-alphabet, second-in"),
            ]
        )

        lines = _sent_payload(client)["embeds"][0]["description"].split("\n")
        assert lines[0].startswith("• **[ZZZZ](")
        assert lines[1].startswith("• **[AAAA](")

    async def test_single_alert_in_batch_uses_singular_title(self):
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch([_payload("AAPL", alert_name="solo")])

        assert _sent_payload(client)["embeds"][0]["title"] == "🔔 1 Alert Triggered"

    async def test_empty_batch_sends_nothing(self):
        client = _mock_client()
        notifier = _notifier(client)

        ok, err = await notifier.send_alert_batch([])

        assert (ok, err) == (True, None)
        client.post.assert_not_awaited()

    async def test_batch_routes_through_post_webhook_and_ships_allowed_mentions(self):
        """The batch sender is a seventh posting method and must not bypass the
        mention-hardening choke point (test_discord_allowed_mentions.py's
        invariant)."""
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch(
            [_payload("AAPL", alert_name="@everyone sell now")]
        )

        assert _sent_payload(client)["allowed_mentions"] == {"parse": []}

    async def test_non_204_response_is_reported_as_failure(self):
        client = _mock_client(status_code=500)
        notifier = _notifier(client)

        ok, err = await notifier.send_alert_batch(
            [_payload("AAPL", alert_name="a"), _payload("MSFT", alert_name="b")]
        )

        assert ok is False
        assert "500" in (err or "")

    async def test_unconfigured_webhook_reports_failure_without_posting(self):
        client = _mock_client()
        notifier = DiscordNotificationService(webhook_url=None)
        notifier._client = client
        notifier._cache_checked = True  # skip the DB lookup

        ok, err = await notifier.send_alert_batch([_payload("A", alert_name="a")])

        assert ok is False and "not configured" in (err or "")
        client.post.assert_not_awaited()

    async def test_condition_override_is_honored_for_entry_zone_lines(self):
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch(
            [
                _payload(
                    "AAPL",
                    alert_name="AAPL zones - T1",
                    condition_type="entry_zone",
                    threshold="180",
                    current="179",
                    condition_override="in entry zone 'T1' ($175.00-$180.00)",
                )
            ]
        )

        assert _sent_payload(client)["embeds"][0]["description"] == (
            "• **[AAPL](https://ic.example.test/equity/AAPL)** — "
            "AAPL zones - T1: in entry zone 'T1' ($175.00-$180.00) (now $179.00)"
        )


class TestDeepLink:
    """One URL per symbol, and the cases where there deliberately is none."""

    @pytest.mark.parametrize(
        "symbol,expected_url",
        [
            ("AAPL", "https://ic.example.test/equity/AAPL"),
            ("BRK.B", "https://ic.example.test/equity/BRK.B"),
            ("SPY", "https://ic.example.test/equity/SPY"),
        ],
    )
    async def test_each_line_links_to_that_symbols_equity_page(
        self, symbol, expected_url
    ):
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch([_payload(symbol, alert_name="x")])

        description = _sent_payload(client)["embeds"][0]["description"]
        assert f"[{symbol}]({expected_url})" in description

    async def test_trailing_slash_on_frontend_url_does_not_double_up(
        self, monkeypatch
    ):
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://ic.example.test/")
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch([_payload("AAPL", alert_name="x")])

        assert (
            "https://ic.example.test/equity/AAPL"
            in _sent_payload(client)["embeds"][0]["description"]
        )
        assert "//equity" not in _sent_payload(client)["embeds"][0]["description"]

    async def test_ratio_alerts_are_not_linked(self):
        """There is no /equity page for a ratio pair (the frontend has
        /ratios, with no per-item route), so a ratio line stays plain bold
        rather than shipping a URL that 404s."""
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch(
            [
                _payload(
                    "GLD/SLV",
                    alert_name="gold-silver",
                    name="Gold / Silver",
                    is_ratio=True,
                    threshold="80",
                    current="82.1234",
                )
            ]
        )

        description = _sent_payload(client)["embeds"][0]["description"]
        # The threshold reads "$80.00" because _get_condition_description
        # price-formats every non-percent condition — pre-existing behaviour
        # that the single-alert embed's description already has (see
        # test_single_ratio_notification_is_not_linked). BZ14 deliberately does
        # not change it; the batched line just matches it.
        assert description == (
            "• **GLD/SLV** — gold-silver: above $80.00 (now 82.1234)"
        )
        assert "/equity/" not in description

    async def test_symbol_cannot_break_out_of_the_markdown_link(self):
        """A symbol carrying markdown-link delimiters must not be able to
        retarget the rendered hyperlink.

        `[LABEL](URL)` ends its label at the first `]`; a following `(` opens a
        new destination. So a raw symbol of `A](https://evil.test)` would
        render as a link reading "A" that points at evil.test, with the real
        equity URL demoted to trailing text. The URL half was already safe
        (percent-encoded via quote(symbol, safe="")); this pins the display
        half. Not reachable from today's data — the only linking path uses
        Equity.symbol, provider-sourced and String(20) — but this is a live
        external send path, so the boundary is asserted rather than argued.
        """
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch(
            [_payload("A](https://evil.test)", alert_name="pwn")]
        )

        description = _sent_payload(client)["embeds"][0]["description"]
        # Hand-authored known-good render. Label: the four delimiters removed
        # from `A](https://evil.test)` leaves `Ahttps://evil.test` (inert text
        # -- Discord does not autolink inside a link label). Destination: the
        # raw symbol percent-encoded with safe="", so `]`->%5D, `(`->%28,
        # `:`->%3A, `/`->%2F, `)`->%29.
        assert description == (
            "• **[Ahttps://evil.test]"
            "(https://ic.example.test/equity/"
            "A%5D%28https%3A%2F%2Fevil.test%29)** "
            "— pwn: above $100.00 (now $105.00)"
        )
        assert "evil.test)" not in description  # no second, attacker destination
        assert description.count("](") == 1  # exactly one link boundary

    @pytest.mark.parametrize("hostile", ["A]B", "A(B", "A)B", "A[B", "A]([)"])
    async def test_link_label_never_contains_link_delimiters(self, hostile):
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch([_payload(hostile, alert_name="x")])

        description = _sent_payload(client)["embeds"][0]["description"]
        label = description.split("**[", 1)[1].split("](", 1)[0]
        assert not set(label) & set("[]()")

    async def test_backslash_cannot_escape_the_generated_closing_bracket(self):
        """Second-round finding: stripping `[]()` alone was bypassable.

        `\\]` is an escaped literal under CommonMark (and Discord's flavour),
        so a symbol ending in a backslash escapes the `]` this code generates:
        the label never closes, no `]` remains on the line, the link construct
        fails to form, and the WHOLE run degrades to plain text. In plain text
        a `<https://evil.co>` span is an autolink Discord renders clickable —
        so the attacker gets a live link and the real equity URL is demoted to
        visible text. The backslash is the load-bearing half (it breaks the
        construct); the angle brackets are what survives in the plain-text
        fallback.
        """
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch(
            [_payload("<https://evil.co>\\", alert_name="pwn")]
        )

        description = _sent_payload(client)["embeds"][0]["description"]
        # Hand-authored known-good render. Label: `<`, `>`, `\` removed from
        # `<https://evil.co>\` leaves `https://evil.co`, inert because the link
        # construct around it is now guaranteed well-formed. Destination: the
        # raw symbol percent-encoded, so `<`->%3C, `>`->%3E, `\`->%5C.
        assert description == (
            "• **[https://evil.co]"
            "(https://ic.example.test/equity/%3Chttps%3A%2F%2Fevil.co%3E%5C)**"
            " — pwn: above $100.00 (now $105.00)"
        )
        assert "\\" not in description  # no escape left to break the bracket
        assert "<" not in description and ">" not in description
        assert description.count("](") == 1

    @pytest.mark.parametrize(
        "hostile,expected_label",
        [
            ("<", None),          # strips to nothing -> placeholder, no link
            ("\\", None),         # ditto
            ("<>", None),
            ("A\\", "A"),         # trailing backslash adjacent to our `]`
            ("<b>", "b"),
            ("A<B", "AB"),
        ],
    )
    async def test_autolink_and_escape_characters_never_reach_the_label(
        self, hostile, expected_label
    ):
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch([_payload(hostile, alert_name="x")])

        description = _sent_payload(client)["embeds"][0]["description"]
        assert "\\" not in description
        assert "<" not in description and ">" not in description
        if expected_label is None:
            assert description.startswith("• **?** —")
            assert "](" not in description
        else:
            label = description.split("**[", 1)[1].split("](", 1)[0]
            assert label == expected_label

    async def test_no_printable_character_can_produce_a_second_link(self):
        """Exhaustive backstop over the printable-ASCII alphabet.

        Two rounds of review each found one more link-producing character
        class (`[]()`, then `\\` and `<>`). Rather than wait for a third, this
        sweeps every printable character through the label and asserts the
        invariant directly: the rendered markup contains exactly one link
        boundary and its label carries none of the characters that can open a
        link or escape our structure.
        """
        import string

        notifier = _notifier(_mock_client())
        offenders = []
        for character in string.printable:
            if character in "\r\n\t\x0b\x0c":
                continue
            markup = notifier._symbol_markup(f"A{character}B", False)
            if markup.count("](") != 1:
                offenders.append((character, markup))
                continue
            label = markup.split("**[", 1)[1].split("](", 1)[0]
            if set(label) & set("[]()<>\\"):
                offenders.append((character, markup))

        assert offenders == []

    async def test_unlinked_branch_bare_url_is_a_known_documented_residual(self):
        """Pins the ONE case stripping deliberately does not cover.

        Discord autolinks a bare `https://…` with no metacharacters at all, so
        the unlinked branch (`**text**`, used for ratios and when FRONTEND_URL
        is unset) can still render a clickable attacker link. Suppressing it
        would mean stripping `:` or `/`, and `/` is required by ratio symbols
        like `GLD/SLV`. Reachable only via a user-authored ratio symbol
        (String(20)), never an equity symbol; and it pre-dates this helper —
        the single-alert description already interpolated target_symbol raw.

        This test documents the accepted behaviour so a future change that
        closes it (an allowlist) fails here loudly rather than silently.
        """
        notifier = _notifier(_mock_client())

        assert notifier._symbol_markup("https://evil.co", True) == (
            "**https://evil.co**"
        )
        # ...while the equity (linked) branch is not exposed to this at all:
        # the bare URL sits inside a guaranteed well-formed label.
        assert notifier._symbol_markup("https://evil.co", False) == (
            "**[https://evil.co]"
            "(https://ic.example.test/equity/https%3A%2F%2Fevil.co)**"
        )

    async def test_unlinked_symbol_is_also_delimiter_stripped(self, monkeypatch):
        """The no-link branch (ratio / unset FRONTEND_URL) gets the same
        treatment, so the two branches can't drift apart."""
        monkeypatch.setattr(settings, "FRONTEND_URL", "")
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch(
            [_payload("A](https://evil.test)", alert_name="x")]
        )

        description = _sent_payload(client)["embeds"][0]["description"]
        assert description == (
            "• **Ahttps://evil.test** — x: above $100.00 (now $105.00)"
        )
        assert "](" not in description

    async def test_symbol_of_only_delimiters_renders_no_link(self):
        """Stripping would leave an empty label, i.e. `[](url)`. Not a real
        symbol; render a placeholder and emit no link at all."""
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch([_payload("[]()", alert_name="x")])

        description = _sent_payload(client)["embeds"][0]["description"]
        assert description == "• **?** — x: above $100.00 (now $105.00)"

    async def test_single_alert_embed_label_is_also_hardened(self):
        """The unbatched path shares _symbol_markup, so it inherits the fix."""
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_notification(
            alert_name="pwn",
            target_symbol="A](https://evil.test)",
            target_name="Evil Corp",
            condition_type="above",
            threshold_value=Decimal("100"),
            current_value=Decimal("105"),
        )

        description = _sent_payload(client)["embeds"][0]["description"]
        label = description.split("**[", 1)[1].split("](", 1)[0]
        assert not set(label) & set("[]()")
        assert "evil.test)" not in description

    async def test_unset_frontend_url_degrades_to_no_link(self, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", "")
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch([_payload("AAPL", alert_name="x")])

        description = _sent_payload(client)["embeds"][0]["description"]
        assert description == "• **AAPL** — x: above $100.00 (now $105.00)"
        assert "](" not in description

    async def test_single_alert_notification_also_deep_links(self):
        """The unbatched (N=1) path keeps its rich embed but gains the link."""
        client = _mock_client()
        notifier = _notifier(client)

        ok, err = await notifier.send_alert_notification(
            alert_name="AAPL breakout",
            target_symbol="AAPL",
            target_name="Apple Inc.",
            condition_type="above",
            threshold_value=Decimal("200"),
            current_value=Decimal("205"),
        )

        assert (ok, err) == (True, None)
        embed = _sent_payload(client)["embeds"][0]
        assert embed["description"] == (
            "**[AAPL](https://ic.example.test/equity/AAPL)** (Apple Inc.) "
            "is above $200.00"
        )
        # The rich single-alert fields are untouched by BZ14.
        assert [f["name"] for f in embed["fields"]] == [
            "Current Value",
            "Threshold",
            "Type",
        ]

    async def test_single_ratio_notification_is_not_linked(self):
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_notification(
            alert_name="gold-silver",
            target_symbol="GLD/SLV",
            target_name="Gold / Silver",
            condition_type="above",
            threshold_value=Decimal("80"),
            current_value=Decimal("82.1234"),
            is_ratio=True,
        )

        description = _sent_payload(client)["embeds"][0]["description"]
        assert description == "**GLD/SLV** (Gold / Silver) is above $80.00"


class TestOversizedBatch:
    """Discord caps an embed description at 4096 chars. Overflow is stated,
    never silently dropped."""

    async def test_overflow_lines_are_summarized_not_silently_dropped(self):
        client = _mock_client()
        notifier = _notifier(client)

        # 200 alerts with long names blows well past 4096 chars.
        alerts = [
            _payload(f"SYM{i:03d}", alert_name="N" * 60) for i in range(200)
        ]

        ok, err = await notifier.send_alert_batch(alerts)

        assert (ok, err) == (True, None)
        description = _sent_payload(client)["embeds"][0]["description"]
        assert len(description) <= 4096
        kept = sum(1 for line in description.split("\n") if line.startswith("• **["))
        assert kept < 200
        assert f"…and {200 - kept} more" in description
        # The count line points at the alerts page so nothing is unreachable.
        assert "https://ic.example.test/alerts" in description

    async def test_long_alert_names_are_truncated_per_line(self):
        client = _mock_client()
        notifier = _notifier(client)

        await notifier.send_alert_batch(
            [_payload("AAPL", alert_name="X" * 200)]
        )

        description = _sent_payload(client)["embeds"][0]["description"]
        assert "X" * 60 + "…" in description
        assert "X" * 61 not in description


# ===========================================================================
# Seam 1 — outbox-drain -> Discord-send
# ===========================================================================


async def _trigger_extra_alert(service, db, symbol: str, price: float = 105.0):
    """Enqueue one more pending delivery on the SAME service (same cycle)."""
    equity = await create_test_equity(db, symbol=symbol)
    alert = await create_test_alert(
        db, equity, condition_type="above", threshold_value=100.0
    )
    service.yahoo = AsyncMock(get_quote=AsyncMock(return_value=_mock_quote(price)))
    await service.process_alert(alert)
    return alert


class TestDrainBatchesOneCycle:
    """Many rows claimed in one drain => ONE Discord send."""

    @patch("app.services.alert.discord_service")
    async def test_three_same_cycle_alerts_send_one_batched_embed(
        self, mock_discord, db
    ):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        mock_discord.send_alert_batch = AsyncMock(return_value=(True, None))

        service, alert_a = await _make_triggered_alert(db, "BAT1")
        await service.process_alert(alert_a)
        alert_b = await _trigger_extra_alert(service, db, "BAT2")
        alert_c = await _trigger_extra_alert(service, db, "BAT3")

        result = await service.deliver_pending()

        assert result == {"claimed": 3, "sent": 3, "failed": 0}
        mock_discord.send_alert_batch.assert_awaited_once()
        mock_discord.send_alert_notification.assert_not_awaited()

        (payloads,), _ = mock_discord.send_alert_batch.await_args
        # Enqueue order, deterministically. created_at is func.now() =
        # TRANSACTION start time in Postgres, so co-enqueued rows tie on it
        # (a 3-tier entry-zone alert writes 3 rows in ONE transaction, and the
        # savepoint-wrapped test fixture ties every row); the claim's `, id`
        # tiebreak is what makes the rendered line order stable rather than
        # planner-dependent.
        assert [p["target_symbol"] for p in payloads] == ["BAT1", "BAT2", "BAT3"]

        for alert in (alert_a, alert_b, alert_c):
            row = (await _deliveries(db, alert.id))[0]
            assert row.status == AlertDeliveryStatus.DELIVERED.value
            assert row.delivered_at is not None
            assert row.lease_expires_at is None

    @patch("app.services.alert.discord_service")
    async def test_lone_alert_still_uses_the_rich_single_embed(
        self, mock_discord, db
    ):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        mock_discord.send_alert_batch = AsyncMock(return_value=(True, None))

        service, alert = await _make_triggered_alert(db, "SOLO1")
        await service.process_alert(alert)

        result = await service.deliver_pending()

        assert result == {"claimed": 1, "sent": 1, "failed": 0}
        mock_discord.send_alert_notification.assert_awaited_once()
        mock_discord.send_alert_batch.assert_not_awaited()

    @patch("app.services.alert.discord_service")
    async def test_failed_batch_leaves_every_member_retryable(
        self, mock_discord, db
    ):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        mock_discord.send_alert_batch = AsyncMock(return_value=(False, "boom"))

        service, alert_a = await _make_triggered_alert(db, "FAIL1")
        await service.process_alert(alert_a)
        alert_b = await _trigger_extra_alert(service, db, "FAIL2")

        result = await service.deliver_pending()

        assert result == {"claimed": 2, "sent": 2 - 2, "failed": 2}
        for alert in (alert_a, alert_b):
            row = (await _deliveries(db, alert.id))[0]
            assert row.status == AlertDeliveryStatus.PENDING.value  # retryable
            assert row.last_error == "boom"
            assert row.attempts == 1
            hist_sent = row.alert_history_id is not None
            assert hist_sent  # the history link survives a failed batch

    @patch("app.services.alert.discord_service")
    async def test_group_cap_chunks_instead_of_dropping(self, mock_discord, db):
        """More pending rows than the group cap => several batched messages,
        never a truncated single one. Nothing is dropped."""
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        mock_discord.send_alert_batch = AsyncMock(return_value=(True, None))

        service, alert_a = await _make_triggered_alert(db, "CAP1")
        await service.process_alert(alert_a)
        for symbol in ("CAP2", "CAP3", "CAP4", "CAP5"):
            await _trigger_extra_alert(service, db, symbol)

        with patch.object(alertmod, "DELIVERY_GROUP_LIMIT", 2):
            result = await service.deliver_pending()

        assert result == {"claimed": 5, "sent": 5, "failed": 0}
        # 2 + 2 + 1 -> two batched sends and one single-alert send.
        assert mock_discord.send_alert_batch.await_count == 2
        assert mock_discord.send_alert_notification.await_count == 1
        batched = [
            len(call.args[0])
            for call in mock_discord.send_alert_batch.await_args_list
        ]
        assert batched == [2, 2]

    @patch("app.services.alert.discord_service")
    async def test_batched_group_is_not_reclaimable_mid_send(
        self, mock_discord, db
    ):
        """Every row in the group holds a live lease for the duration of the
        single batched POST, so a concurrent drain finds nothing."""
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))

        service, alert_a = await _make_triggered_alert(db, "LEASE1")
        await service.process_alert(alert_a)
        await _trigger_extra_alert(service, db, "LEASE2")

        reclaims_during_send = []

        async def send_and_probe(payloads):
            reclaims_during_send.append(
                await service.claim_pending_deliveries(lease_seconds=120)
            )
            return (True, None)

        mock_discord.send_alert_batch = AsyncMock(side_effect=send_and_probe)

        result = await service.deliver_pending()

        assert result == {"claimed": 2, "sent": 2, "failed": 0}
        assert reclaims_during_send == [[]]
