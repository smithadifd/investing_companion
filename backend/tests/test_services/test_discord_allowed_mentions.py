"""Regression: every Discord webhook POST carries allowed_mentions: {"parse": []}.

Defense-in-depth *under* the per-agent mention-sanitization layers (#209
strategy-brief, #210 catalysts, #211 trade-journal): even if untrusted text
(news headlines, LLM narratives) makes it to a payload with mention syntax
intact, Discord itself is told to resolve zero mentions into pings. Those
sanitizers stay in place and are not touched or weakened here - this is a
second, independent layer at the send choke point (``_post_webhook``), which
all six webhook-posting methods on ``DiscordNotificationService`` route
through.

No test in this module performs real network I/O: every ``DiscordNotification
Service`` under test has its ``httpx.AsyncClient`` replaced by a mock before
any send method is called, and the module-level ``_forbid_real_client``
fixture makes constructing a *real* ``httpx.AsyncClient`` raise - so if the
mock-injection ever silently failed and a send method fell back to a real
network-capable client, every test in this file would fail loudly instead of
quietly doing a live POST.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.notifications.discord import DiscordNotificationService

WEBHOOK_URL = "https://discord.com/api/webhooks/123456789/test-token"


@pytest.fixture(autouse=True)
def _forbid_real_client(monkeypatch):
    """Guard: fail loudly if any code path in this module tries to construct
    a real httpx.AsyncClient. Every test injects a mock client directly via
    `notifier._client`, so `_get_client()` should never reach its
    `httpx.AsyncClient(...)` construction branch. If it ever does - e.g. a
    future refactor drops the injected mock somewhere - this turns a silent
    live-network POST into an immediate test failure.
    """

    def _boom(*args, **kwargs):
        raise AssertionError(
            "real httpx.AsyncClient must never be constructed in "
            "test_discord_allowed_mentions.py - a mock client should "
            "always be injected first"
        )

    monkeypatch.setattr(httpx, "AsyncClient", _boom)


def _mock_client(status_code: int = 204) -> MagicMock:
    """A mock httpx.AsyncClient whose .post() is an AsyncMock returning a
    fake 204 response, capturing call args for payload assertions."""
    response = MagicMock()
    response.status_code = status_code
    response.text = ""
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    return client


def _notifier(client: MagicMock) -> DiscordNotificationService:
    """A DiscordNotificationService with a webhook URL pre-set (env-style,
    skips the DB lookup path) and a mock client pre-injected (skips the
    real-client construction branch in `_get_client()`)."""
    notifier = DiscordNotificationService(webhook_url=WEBHOOK_URL)
    notifier._client = client
    return notifier


def _sent_payload(client: MagicMock) -> dict:
    """The JSON payload from the most recent client.post() call."""
    _, kwargs = client.post.call_args
    return kwargs["json"]


# ---------------------------------------------------------------------------
# Unit tests: the helper itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_webhook_helper_injects_empty_parse():
    client = _mock_client()
    notifier = _notifier(client)

    response = await notifier._post_webhook(WEBHOOK_URL, {"content": "hello"})

    assert response.status_code == 204
    client.post.assert_awaited_once()
    args, kwargs = client.post.call_args
    assert args[0] == WEBHOOK_URL
    payload = kwargs["json"]
    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["content"] == "hello"


@pytest.mark.asyncio
async def test_post_webhook_helper_overrides_preexisting_allowed_mentions():
    """The helper is the single source of truth for the field - even if a
    caller's payload already set something else, the empty-parse policy
    wins."""
    client = _mock_client()
    notifier = _notifier(client)

    await notifier._post_webhook(
        WEBHOOK_URL, {"content": "x", "allowed_mentions": {"parse": ["users"]}}
    )

    payload = _sent_payload(client)
    assert payload["allowed_mentions"] == {"parse": []}


@pytest.mark.asyncio
async def test_post_webhook_helper_does_not_mutate_caller_payload():
    """The helper must not mutate the dict passed in by the caller (it builds
    a new hardened dict) - a caller that inspects its own `payload` variable
    after the call should not see the injected key."""
    client = _mock_client()
    notifier = _notifier(client)

    original_payload = {"content": "hi"}
    await notifier._post_webhook(WEBHOOK_URL, original_payload)

    assert original_payload == {"content": "hi"}


# ---------------------------------------------------------------------------
# All six posting methods route through the helper and ship the field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_alert_notification_payload_has_empty_parse():
    client = _mock_client()
    notifier = _notifier(client)

    ok, err = await notifier.send_alert_notification(
        alert_name="AAPL breakout",
        target_symbol="AAPL",
        target_name="Apple Inc.",
        condition_type="above",
        threshold_value=200,
        current_value=205,
    )

    assert (ok, err) == (True, None)
    client.post.assert_awaited_once()
    payload = _sent_payload(client)
    assert payload["allowed_mentions"] == {"parse": []}
    assert "embeds" in payload


@pytest.mark.asyncio
async def test_send_test_notification_payload_has_empty_parse():
    client = _mock_client()
    notifier = _notifier(client)

    ok, err = await notifier.send_test_notification()

    assert (ok, err) == (True, None)
    client.post.assert_awaited_once()
    payload = _sent_payload(client)
    assert payload["allowed_mentions"] == {"parse": []}
    assert "embeds" in payload


@pytest.mark.asyncio
async def test_send_plain_text_payload_has_empty_parse():
    client = _mock_client()
    notifier = _notifier(client)

    ok, err = await notifier.send_plain_text("weekly journal is ready")

    assert (ok, err) == (True, None)
    client.post.assert_awaited_once()
    payload = _sent_payload(client)
    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["content"] == "weekly journal is ready"


@pytest.mark.asyncio
async def test_send_movers_summary_payload_has_empty_parse():
    client = _mock_client()
    notifier = _notifier(client)

    # Needs at least one mover past the threshold, else the method
    # short-circuits before ever building a payload / posting.
    gainers = [
        {
            "symbol": "NVDA",
            "name": "NVIDIA",
            "price": 900.0,
            "change_percent": 7.5,
            "watchlist_name": "Tech",
        }
    ]

    ok, err = await notifier.send_movers_summary(
        gainers=gainers,
        losers=[],
        threshold_percent=5.0,
        total_items=20,
        watchlist_count=1,
    )

    assert (ok, err) == (True, None)
    client.post.assert_awaited_once()
    payload = _sent_payload(client)
    assert payload["allowed_mentions"] == {"parse": []}
    assert "embeds" in payload


@pytest.mark.asyncio
async def test_send_upcoming_events_payload_has_empty_parse():
    client = _mock_client()
    notifier = _notifier(client)

    events = [
        {
            "event_date": "2026-07-20",
            "title": "AAPL Earnings",
            "event_type": "earnings",
            "symbol": "AAPL",
        }
    ]

    ok, err = await notifier.send_upcoming_events(events=events)

    assert (ok, err) == (True, None)
    client.post.assert_awaited_once()
    payload = _sent_payload(client)
    assert payload["allowed_mentions"] == {"parse": []}
    assert "embeds" in payload


@pytest.mark.asyncio
async def test_send_end_of_day_summary_payload_has_empty_parse():
    client = _mock_client()
    notifier = _notifier(client)

    ok, err = await notifier.send_end_of_day_summary(
        gainers=[],
        losers=[],
        threshold_percent=5.0,
        total_items=10,
        watchlist_count=1,
        alerts_triggered=2,
        active_alerts=5,
        top_triggers=[{"name": "AAPL above 200", "count": 2}],
    )

    assert (ok, err) == (True, None)
    client.post.assert_awaited_once()
    payload = _sent_payload(client)
    assert payload["allowed_mentions"] == {"parse": []}
    assert "embeds" in payload


# ---------------------------------------------------------------------------
# Explicit routing proof: each method calls _post_webhook, not client.post
# directly (guards against a future edit re-introducing a raw client.post
# bypass in any one of the six methods).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_six_methods_route_through_post_webhook_helper(monkeypatch):
    client = _mock_client()
    notifier = _notifier(client)

    spy = AsyncMock(wraps=notifier._post_webhook)
    monkeypatch.setattr(notifier, "_post_webhook", spy)

    await notifier.send_alert_notification(
        alert_name="A",
        target_symbol="AAPL",
        target_name="Apple",
        condition_type="above",
        threshold_value=1,
        current_value=2,
    )
    await notifier.send_test_notification()
    await notifier.send_plain_text("hi")
    await notifier.send_movers_summary(
        gainers=[{"symbol": "X", "price": 1, "change_percent": 10}],
        losers=[],
        threshold_percent=5.0,
        total_items=1,
        watchlist_count=1,
    )
    await notifier.send_upcoming_events(
        events=[{"event_date": "2026-07-20", "title": "T", "event_type": "earnings"}]
    )
    await notifier.send_end_of_day_summary(
        gainers=[],
        losers=[],
        threshold_percent=5.0,
        total_items=1,
        watchlist_count=1,
        alerts_triggered=0,
        active_alerts=0,
        top_triggers=[],
    )

    assert spy.await_count == 6
    # Every call the spy wrapped also actually reached the mock client -
    # proving _post_webhook (not some other path) is what talks to the wire.
    assert client.post.await_count == 6


# ---------------------------------------------------------------------------
# Belt-over-braces: mention syntax that somehow reaches the send layer still
# ships with the empty-parse field (the scenario is a sanitizer regression or
# an untrusted-text path that forgot to call the per-agent neutralizer - the
# #33 codex HIGH class of bug). #209/#210/#211's text-level neutralization is
# a separate, independent layer and is not exercised or bypassed here.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_text",
    [
        "@everyone the market is crashing, sell now",
        "@here check this out",
        "ping <@123456789012345678> about this trade",
        "notify <@&987654321098765432> role about the alert",
        "unsanitized DOE announcement: @everyone reserve program",
    ],
)
async def test_send_plain_text_with_raw_mention_syntax_still_has_empty_parse(
    raw_text,
):
    client = _mock_client()
    notifier = _notifier(client)

    ok, err = await notifier.send_plain_text(raw_text)

    assert (ok, err) == (True, None)
    payload = _sent_payload(client)
    # Content is passed through unchanged by this layer - mention-syntax
    # neutralization is #210/#211's job, not the send layer's. The send
    # layer's guarantee is independent: Discord is told to parse zero
    # mentions regardless of what the content contains.
    assert payload["content"] == raw_text
    assert payload["allowed_mentions"] == {"parse": []}


@pytest.mark.asyncio
async def test_send_alert_notification_with_mention_syntax_in_notes_still_has_empty_parse():
    client = _mock_client()
    notifier = _notifier(client)

    ok, err = await notifier.send_alert_notification(
        alert_name="A",
        target_symbol="AAPL",
        target_name="Apple",
        condition_type="above",
        threshold_value=1,
        current_value=2,
        notes="@everyone this note contains a raw mention <@123>",
    )

    assert (ok, err) == (True, None)
    payload = _sent_payload(client)
    assert payload["allowed_mentions"] == {"parse": []}


# ---------------------------------------------------------------------------
# Non-network-fallback guard, made explicit as its own assertion (in addition
# to the autouse fixture firing on any violation across the whole module).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_client_returns_injected_mock_without_constructing_real_client():
    client = _mock_client()
    notifier = _notifier(client)

    resolved = await notifier._get_client()

    assert resolved is client
    # httpx.AsyncClient is monkeypatched to raise by the autouse fixture; if
    # `_get_client()` had fallen back to constructing a real client instead
    # of returning the injected mock, this test would already have raised
    # before reaching this assertion.
