"""Tests for the Daily Strategy Brief agent (T1 sub-PR 4/4, docs/issues/014).

Covers, without live network/LLM calls (mocked throughout, matching
tests/test_services/test_ai.py's style):
  * ET signal_date resolution around the UTC/ET day boundary (both EST/EDT)
  * Discord 2000-char truncation
  * the binding 2%-of-nearest-bound "near zone" rule
  * the LLM prompt renders every computed number verbatim (nothing invented)
  * quote-fetch bounds: dedupe, 30-symbol cap, concurrency<=5, per-call
    timeout, provider always closed, failed/omitted symbols recorded
  * per-source context degradation (one failing collector doesn't sink the
    others)
  * regenerate-in-place upsert + same-day Discord dedup
  * the LLM-failure posture: no row, no Discord
  * model resolution precedence

DB-backed tests use the ``db``/factories fixtures (live Postgres, no Redis
needed - budget/discord/quote-provider are faked).
"""

import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from app.db.models.strategy_signal import StrategySignal
from app.schemas.watchlist import EntryZone
from app.services.agents import strategy_brief as sb
from tests.factories import create_test_user

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeBudget:
    """Injectable budget double (mirrors test_ai.py's FakeBudget)."""

    def __init__(self) -> None:
        self.recorded: list[tuple] = []

    async def check(self, user_id):  # pragma: no cover - not exercised here
        pass

    async def record(self, user_id, tokens):
        self.recorded.append((user_id, tokens))


class FakeDiscordService:
    """Injectable Discord double: records every send_plain_text call."""

    def __init__(self, success: bool = True, error: str | None = None) -> None:
        self.sent: list[str] = []
        self._success = success
        self._error = error

    async def send_plain_text(self, message: str):
        self.sent.append(message)
        return self._success, self._error


class FakeExtendedQuoteProvider:
    """Injectable extended-quote provider: records calls, tracks concurrency."""

    def __init__(self, responses=None, delays=None, raise_for=None, base_delay: float = 0.0):
        self.responses = responses or {}
        self.delays = delays or {}
        self.raise_for = raise_for or set()
        self.base_delay = base_delay
        self.calls: list[str] = []
        self.close_calls = 0
        self._in_flight = 0
        self.max_in_flight = 0
        self._lock = asyncio.Lock()

    async def get_extended_quote(self, symbol: str):
        self.calls.append(symbol)
        async with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            delay = self.delays.get(symbol, self.base_delay)
            if delay:
                await asyncio.sleep(delay)
            if symbol in self.raise_for:
                raise RuntimeError(f"boom:{symbol}")
            return self.responses.get(symbol)
        finally:
            async with self._lock:
                self._in_flight -= 1

    async def aclose(self):
        self.close_calls += 1


def _empty_context(signal_date: str = "2026-07-18") -> dict:
    return {
        "schema_version": 1,
        "signal_date": signal_date,
        "symbols": [],
        "quotes": {},
        "zone_proximity": [],
        "alerts": [],
        "events": [],
        "needs_attention": [],
        "news": [],
        "unavailable_sources": [],
    }


# ---------------------------------------------------------------------------
# _today_et - ET day boundary around midnight UTC
# ---------------------------------------------------------------------------
def test_today_et_before_est_offset_rolls_to_previous_day():
    # January = EST (UTC-5); 03:00 UTC = 22:00 ET the day before.
    now_utc = datetime(2026, 1, 15, 3, 0, tzinfo=timezone.utc)
    assert sb._today_et(now_utc) == date(2026, 1, 14)


def test_today_et_after_est_offset_is_same_day():
    now_utc = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)  # 07:00 ET
    assert sb._today_et(now_utc) == date(2026, 1, 15)


def test_today_et_edt_offset_around_midnight_utc():
    # July = EDT (UTC-4); 03:30 UTC = 23:30 ET the day before.
    now_utc = datetime(2026, 7, 18, 3, 30, tzinfo=timezone.utc)
    assert sb._today_et(now_utc) == date(2026, 7, 17)


def test_today_et_defaults_to_real_clock_when_omitted():
    assert isinstance(sb._today_et(), date)


# ---------------------------------------------------------------------------
# _truncate_for_discord
# ---------------------------------------------------------------------------
def test_truncate_short_message_untouched():
    assert sb._truncate_for_discord("hello") == "hello"


def test_truncate_long_message_fits_discord_limit():
    result = sb._truncate_for_discord("x" * 2500)
    assert len(result) == sb.DISCORD_CHAR_LIMIT
    assert result.endswith("...")


def test_truncate_exactly_at_limit_untouched():
    text = "x" * sb.DISCORD_CHAR_LIMIT
    assert sb._truncate_for_discord(text) == text


# ---------------------------------------------------------------------------
# Near-zone rule (binding: within 2% of nearest bound, or inside the zone)
# ---------------------------------------------------------------------------
def test_zone_in_zone_status():
    zone = EntryZone(tier="Full", low=Decimal("48"), high=Decimal("50"))
    status, _distance = sb._nearest_boundary_distance(Decimal("49"), zone)
    assert status == "in_zone"


def test_zone_near_within_threshold():
    zone = EntryZone(tier="Full", low=Decimal("48"), high=Decimal("50"))
    status, distance = sb._nearest_boundary_distance(Decimal("50.90"), zone)
    assert status == "near"
    assert distance == Decimal("-1.77")


def test_zone_far_outside_threshold():
    zone = EntryZone(tier="Full", low=Decimal("48"), high=Decimal("50"))
    status, _distance = sb._nearest_boundary_distance(Decimal("60"), zone)
    assert status == "far"


def test_compute_zone_proximity_filters_to_near_and_in_zone_only():
    items = [
        {
            "symbol": "CCJ",
            "entry_zones": [EntryZone(tier="Full", low=Decimal("48"), high=Decimal("50"))],
        },
        {
            "symbol": "FAR",
            "entry_zones": [EntryZone(tier="Full", low=Decimal("10"), high=Decimal("12"))],
        },
        {"symbol": "NOZONE", "entry_zones": []},
    ]
    quotes = {
        "CCJ": {"price": 49.5, "change_percent": 1.0, "session": "regular"},
        "FAR": {"price": 100.0, "change_percent": 0.0, "session": "regular"},
    }

    result = sb._compute_zone_proximity(items, quotes)

    assert [r["symbol"] for r in result] == ["CCJ"]
    assert result[0]["status"] == "in_zone"
    assert result[0]["tier"] == "Full"


def test_compute_zone_proximity_skips_symbols_without_a_quote():
    items = [
        {
            "symbol": "NOQUOTE",
            "entry_zones": [EntryZone(tier="Full", low=Decimal("48"), high=Decimal("50"))],
        }
    ]
    assert sb._compute_zone_proximity(items, {}) == []


# ---------------------------------------------------------------------------
# _build_prompt - numbers passed, not invented
# ---------------------------------------------------------------------------
def test_prompt_contains_every_computed_number_verbatim():
    context = {
        "signal_date": "2026-07-20",
        "symbols": ["SPY", "CCJ"],
        "quotes": {
            "SPY": {"price": 512.34, "change_percent": -0.42, "session": "pre"},
            "CCJ": {"price": 49.87, "change_percent": 1.15, "session": "regular"},
        },
        "zone_proximity": [
            {
                "symbol": "CCJ",
                "tier": "Full",
                "low": 48.0,
                "high": 50.0,
                "status": "near",
                "distance_percent": 0.26,
            }
        ],
        "alerts": [
            {
                "symbol": "UUUU",
                "condition_type": "above",
                "threshold_value": 12.5,
                "status": "approaching",
                "distance_percent": -2.31,
            }
        ],
        "events": [
            {
                "title": "UUUU Earnings",
                "event_time": "16:30:00",
                "importance": "high",
                "event_type": "earnings",
                "symbol": "UUUU",
            }
        ],
        "needs_attention": ["\U0001f514 CCJ triggered"],
        "news": [],
        "unavailable_sources": [],
    }

    prompt = sb._build_prompt(context)

    assert "512.34" in prompt
    assert "-0.42%" in prompt
    assert "49.87" in prompt
    assert "+0.26%" in prompt
    assert "12.5" in prompt
    assert "-2.31%" in prompt
    assert "16:30:00" in prompt
    assert "CCJ triggered" in prompt
    assert "Do not invent" in prompt


def test_prompt_omits_empty_sections():
    prompt = sb._build_prompt(_empty_context())
    assert "Watchlist quotes" not in prompt
    assert "Active alerts" not in prompt
    assert "Today's calendar" not in prompt


# ---------------------------------------------------------------------------
# _fetch_quotes - binding quote bounds
# ---------------------------------------------------------------------------
async def test_fetch_quotes_dedupes_and_caps_at_30(monkeypatch):
    unique_symbols = [f"SYM{i}" for i in range(35)]
    symbols = unique_symbols + ["SYM0", "SYM1"]  # duplicates thrown in
    provider = FakeExtendedQuoteProvider(
        responses={
            s: {"price": 10.0, "change_percent": 0.0, "session": "regular"} for s in unique_symbols
        }
    )
    monkeypatch.setattr(sb, "get_extended_quote_provider", AsyncMock(return_value=provider))

    quotes, unavailable = await sb._fetch_quotes(MagicMock(), symbols)

    assert len(provider.calls) == 30
    assert len(set(provider.calls)) == 30
    assert "quotes:capped:5" in unavailable
    assert len(quotes) == 30


async def test_fetch_quotes_bounds_concurrency(monkeypatch):
    symbols = [f"SYM{i}" for i in range(12)]
    provider = FakeExtendedQuoteProvider(
        responses={s: {"price": 10.0, "change_percent": 0.0, "session": "regular"} for s in symbols},
        base_delay=0.02,
    )
    monkeypatch.setattr(sb, "get_extended_quote_provider", AsyncMock(return_value=provider))

    await sb._fetch_quotes(MagicMock(), symbols)

    assert provider.max_in_flight <= sb.QUOTE_CONCURRENCY
    assert provider.max_in_flight > 1  # actually concurrent, not serialized


async def test_fetch_quotes_per_call_timeout_marks_symbol_unavailable(monkeypatch):
    monkeypatch.setattr(sb, "QUOTE_TIMEOUT_SECONDS", 0.05)
    provider = FakeExtendedQuoteProvider(
        responses={
            "SLOW": {"price": 10.0, "change_percent": 0.0, "session": "regular"},
            "FAST": {"price": 20.0, "change_percent": 0.0, "session": "regular"},
        },
        delays={"SLOW": 0.3},
    )
    monkeypatch.setattr(sb, "get_extended_quote_provider", AsyncMock(return_value=provider))

    quotes, unavailable = await sb._fetch_quotes(MagicMock(), ["SLOW", "FAST"])

    assert "FAST" in quotes
    assert "SLOW" not in quotes
    assert "quote:SLOW" in unavailable


async def test_fetch_quotes_records_failed_symbol_and_always_closes_provider(monkeypatch):
    provider = FakeExtendedQuoteProvider(
        responses={"OK": {"price": 5.0, "change_percent": 0.0, "session": "regular"}},
        raise_for={"BAD"},
    )
    monkeypatch.setattr(sb, "get_extended_quote_provider", AsyncMock(return_value=provider))

    quotes, unavailable = await sb._fetch_quotes(MagicMock(), ["OK", "BAD"])

    assert "OK" in quotes
    assert "quote:BAD" in unavailable
    assert provider.close_calls == 1


async def test_fetch_quotes_missing_quote_recorded_as_unavailable(monkeypatch):
    provider = FakeExtendedQuoteProvider(responses={"NONE": None})
    monkeypatch.setattr(sb, "get_extended_quote_provider", AsyncMock(return_value=provider))

    quotes, unavailable = await sb._fetch_quotes(MagicMock(), ["NONE"])

    assert quotes == {}
    assert "quote:NONE" in unavailable


async def test_fetch_quotes_empty_symbols_skips_provider_entirely(monkeypatch):
    mock_get_provider = AsyncMock()
    monkeypatch.setattr(sb, "get_extended_quote_provider", mock_get_provider)

    quotes, unavailable = await sb._fetch_quotes(MagicMock(), [])

    assert quotes == {}
    assert unavailable == []
    mock_get_provider.assert_not_awaited()


# ---------------------------------------------------------------------------
# _assemble_context - per-source degradation
# ---------------------------------------------------------------------------
async def test_assemble_context_degrades_failing_section_but_keeps_others(monkeypatch):
    monkeypatch.setattr(
        sb, "_collect_watchlist_items", AsyncMock(return_value=[{"symbol": "CCJ", "entry_zones": []}])
    )
    monkeypatch.setattr(
        sb,
        "_fetch_quotes",
        AsyncMock(
            return_value=(
                {"CCJ": {"price": 49.5, "change_percent": 1.0, "session": "regular"}},
                [],
            )
        ),
    )
    monkeypatch.setattr(
        sb,
        "_collect_alerts",
        AsyncMock(
            return_value=[
                {
                    "symbol": "CCJ",
                    "name": "CCJ alert",
                    "condition_type": "above",
                    "threshold_value": 1.0,
                    "last_checked_value": None,
                    "distance_percent": None,
                    "status": "armed",
                }
            ]
        ),
    )
    monkeypatch.setattr(sb, "_collect_events", AsyncMock(side_effect=RuntimeError("calendar down")))
    monkeypatch.setattr(sb, "_collect_needs_attention", AsyncMock(return_value=["⚡ something"]))
    monkeypatch.setattr(sb, "_collect_news", AsyncMock(return_value=[]))

    context = await sb._assemble_context(MagicMock(), uuid.uuid4(), date(2026, 7, 20))

    assert context["events"] == []
    assert "events" in context["unavailable_sources"]
    assert context["alerts"]  # still populated despite the events failure
    assert context["needs_attention"] == ["⚡ something"]
    assert context["quotes"]["CCJ"]["price"] == 49.5


async def test_assemble_context_watchlist_failure_still_produces_context(monkeypatch):
    monkeypatch.setattr(sb, "_collect_watchlist_items", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(sb, "_fetch_quotes", AsyncMock(return_value=({}, [])))
    monkeypatch.setattr(sb, "_collect_alerts", AsyncMock(return_value=[]))
    monkeypatch.setattr(sb, "_collect_events", AsyncMock(return_value=[]))
    monkeypatch.setattr(sb, "_collect_needs_attention", AsyncMock(return_value=[]))
    monkeypatch.setattr(sb, "_collect_news", AsyncMock(return_value=[]))

    context = await sb._assemble_context(MagicMock(), uuid.uuid4(), date(2026, 7, 20))

    assert context["symbols"] == []
    assert "watchlist" in context["unavailable_sources"]


# ---------------------------------------------------------------------------
# _upsert_signal - regenerate in place + same-day Discord dedup signal
# ---------------------------------------------------------------------------
async def test_upsert_signal_creates_new_row_and_signals_send(db):
    user = await create_test_user(db, email="strat-upsert-1@example.com")
    today = date(2026, 7, 18)

    should_send = await sb._upsert_signal(db, user.id, today, "Brief A", {"schema_version": 1})

    assert should_send is True
    row = (
        await db.execute(select(StrategySignal).where(StrategySignal.user_id == user.id))
    ).scalar_one()
    assert row.content == "Brief A"
    assert row.signal_date == today


async def test_upsert_signal_identical_rerun_does_not_resend(db):
    user = await create_test_user(db, email="strat-upsert-2@example.com")
    today = date(2026, 7, 18)
    await sb._upsert_signal(db, user.id, today, "Brief A", {"schema_version": 1})

    should_send = await sb._upsert_signal(db, user.id, today, "Brief A", {"schema_version": 1})

    assert should_send is False
    rows = (
        (await db.execute(select(StrategySignal).where(StrategySignal.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1  # regenerated in place, never duplicated


async def test_upsert_signal_changed_content_regenerates_in_place_and_resends(db):
    user = await create_test_user(db, email="strat-upsert-3@example.com")
    today = date(2026, 7, 18)
    await sb._upsert_signal(db, user.id, today, "Brief A", {"schema_version": 1})

    should_send = await sb._upsert_signal(db, user.id, today, "Brief B", {"schema_version": 1})

    assert should_send is True
    rows = (
        (await db.execute(select(StrategySignal).where(StrategySignal.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].content == "Brief B"


# ---------------------------------------------------------------------------
# _resolve_model - never hardcode, never resolve to a retired id
# ---------------------------------------------------------------------------
def test_resolve_model_prefers_explicit_default(monkeypatch):
    monkeypatch.setattr(sb.app_config, "AI_DEFAULT_MODEL", "claude-sonnet-5")
    assert sb._resolve_model("claude-opus-4-8") == "claude-opus-4-8"


def test_resolve_model_falls_back_to_app_default(monkeypatch):
    monkeypatch.setattr(sb.app_config, "AI_DEFAULT_MODEL", "claude-haiku-4-5-20251001")
    assert sb._resolve_model(None) == "claude-haiku-4-5-20251001"


def test_resolve_model_unknown_ids_fall_through_to_sonnet(monkeypatch):
    monkeypatch.setattr(sb.app_config, "AI_DEFAULT_MODEL", "claude-3-5-retired")
    assert sb._resolve_model("also-unknown") == "claude-sonnet-5"


# ---------------------------------------------------------------------------
# _compose_brief - the LLM step in isolation
# ---------------------------------------------------------------------------
def _fake_anthropic(text: str = "**Daily Strategy Brief**\n- Sit tight.", in_tok=100, out_tok=50):
    message = MagicMock()
    message.content = [MagicMock(text=text)]
    message.usage = MagicMock(input_tokens=in_tok, output_tokens=out_tok)
    client = MagicMock()
    client.messages.create.return_value = message
    return client


async def test_compose_brief_records_tokens_on_success(monkeypatch):
    monkeypatch.setattr(
        sb.AIService, "get_settings", AsyncMock(return_value=MagicMock(default_model=None))
    )
    budget = FakeBudget()
    uid = uuid.uuid4()
    client = _fake_anthropic()

    with patch("anthropic.Anthropic", return_value=client):
        text = await sb._compose_brief(MagicMock(), uid, "sk-test", _empty_context(), budget=budget)

    assert text == "**Daily Strategy Brief**\n- Sit tight."
    assert budget.recorded == [(uid, 150)]


async def test_compose_brief_returns_none_on_llm_exception(monkeypatch):
    monkeypatch.setattr(
        sb.AIService, "get_settings", AsyncMock(return_value=MagicMock(default_model=None))
    )
    with patch("anthropic.Anthropic", side_effect=RuntimeError("network down")):
        result = await sb._compose_brief(MagicMock(), uuid.uuid4(), "sk-test", _empty_context())

    assert result is None


async def test_compose_brief_returns_none_on_empty_response(monkeypatch):
    monkeypatch.setattr(
        sb.AIService, "get_settings", AsyncMock(return_value=MagicMock(default_model=None))
    )
    client = _fake_anthropic(text="   ")

    with patch("anthropic.Anthropic", return_value=client):
        result = await sb._compose_brief(MagicMock(), uuid.uuid4(), "sk-test", _empty_context())

    assert result is None


# ---------------------------------------------------------------------------
# StrategyBriefAgent.execute - end-to-end wiring
# ---------------------------------------------------------------------------
async def test_execute_llm_failure_writes_no_row_and_sends_no_discord(db, monkeypatch):
    user = await create_test_user(db, email="strat-exec-fail@example.com")
    monkeypatch.setattr(sb.AIService, "get_api_key", AsyncMock(return_value="sk-test"))
    monkeypatch.setattr(sb, "_assemble_context", AsyncMock(return_value=_empty_context()))
    monkeypatch.setattr(sb, "_compose_brief", AsyncMock(return_value=None))

    fake_discord = FakeDiscordService()
    agent = sb.StrategyBriefAgent(budget=FakeBudget(), discord=fake_discord)

    await agent.execute(db, user.id)

    rows = (
        (await db.execute(select(StrategySignal).where(StrategySignal.user_id == user.id)))
        .scalars()
        .all()
    )
    assert rows == []
    assert fake_discord.sent == []


async def test_execute_aborts_quietly_when_api_key_missing_at_execute_time(db, monkeypatch):
    user = await create_test_user(db, email="strat-exec-nokey@example.com")
    monkeypatch.setattr(sb.AIService, "get_api_key", AsyncMock(return_value=None))
    compose_mock = AsyncMock()
    monkeypatch.setattr(sb, "_compose_brief", compose_mock)

    agent = sb.StrategyBriefAgent(budget=FakeBudget(), discord=FakeDiscordService())
    await agent.execute(db, user.id)

    compose_mock.assert_not_awaited()
    rows = (
        (await db.execute(select(StrategySignal).where(StrategySignal.user_id == user.id)))
        .scalars()
        .all()
    )
    assert rows == []


async def test_execute_happy_path_persists_and_sends_then_skips_duplicate_send(db, monkeypatch):
    user = await create_test_user(db, email="strat-exec-happy@example.com")
    monkeypatch.setattr(sb.AIService, "get_api_key", AsyncMock(return_value="sk-test"))
    monkeypatch.setattr(sb, "_assemble_context", AsyncMock(return_value=_empty_context()))
    monkeypatch.setattr(
        sb, "_compose_brief", AsyncMock(return_value="**Daily Strategy Brief**\n- Sit tight.")
    )

    fake_discord = FakeDiscordService()
    agent = sb.StrategyBriefAgent(budget=FakeBudget(), discord=fake_discord)

    await agent.execute(db, user.id)  # first run: new row, sends
    await agent.execute(db, user.id)  # same-day rerun, identical narrative: no resend

    rows = (
        (await db.execute(select(StrategySignal).where(StrategySignal.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert len(fake_discord.sent) == 1


async def test_execute_changed_narrative_regenerates_and_resends(db, monkeypatch):
    user = await create_test_user(db, email="strat-exec-changed@example.com")
    monkeypatch.setattr(sb.AIService, "get_api_key", AsyncMock(return_value="sk-test"))
    monkeypatch.setattr(sb, "_assemble_context", AsyncMock(return_value=_empty_context()))
    compose_mock = AsyncMock(
        side_effect=["**Brief v1**\n- Hold.", "**Brief v2**\n- New catalyst, reassess."]
    )
    monkeypatch.setattr(sb, "_compose_brief", compose_mock)

    fake_discord = FakeDiscordService()
    agent = sb.StrategyBriefAgent(budget=FakeBudget(), discord=fake_discord)

    await agent.execute(db, user.id)
    await agent.execute(db, user.id)

    rows = (
        (await db.execute(select(StrategySignal).where(StrategySignal.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1  # regenerated in place, not duplicated
    assert rows[0].content == "**Brief v2**\n- New catalyst, reassess."
    assert len(fake_discord.sent) == 2  # content changed -> resent


async def test_execute_discord_failure_is_logged_and_swallowed(db, monkeypatch):
    """A Discord send failure must not raise - the row is already committed."""
    user = await create_test_user(db, email="strat-exec-discord-fail@example.com")
    monkeypatch.setattr(sb.AIService, "get_api_key", AsyncMock(return_value="sk-test"))
    monkeypatch.setattr(sb, "_assemble_context", AsyncMock(return_value=_empty_context()))
    monkeypatch.setattr(sb, "_compose_brief", AsyncMock(return_value="**Brief**\n- Hold."))

    fake_discord = FakeDiscordService(success=False, error="webhook not configured")
    agent = sb.StrategyBriefAgent(budget=FakeBudget(), discord=fake_discord)

    await agent.execute(db, user.id)  # must not raise

    row = (
        await db.execute(select(StrategySignal).where(StrategySignal.user_id == user.id))
    ).scalar_one()
    assert row.content == "**Brief**\n- Hold."
