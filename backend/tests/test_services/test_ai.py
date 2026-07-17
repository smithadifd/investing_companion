"""Tests for the AI analysis revival (Queue S S5).

Covers, without live infra (Postgres/Redis mocked or faked):
  * current model ids + configurable default resolution
  * the encrypted-accessor key read (converged onto SettingsService)
  * the WATCHLIST/GENERAL decision (IMPLEMENTED — new branches exercised)
  * the Redis response cache (hit on repeat)
  * the per-day token budget (fails closed at the ceiling)
  * SSE `data: …\n\n` framing (the endpoint formatter)
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.endpoints.ai import format_sse
from app.core.config import settings
from app.schemas.ai import (
    AIAnalysisRequest,
    AIModel,
    AISettingsResponse,
    AnalysisType,
    WatchlistContext,
    WatchlistHolding,
)
from app.services.ai import AIService, _usage_tokens
from app.services.ai_budget import AITokenBudget, BudgetExceededError
from app.services.settings import SettingsService


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeCache:
    """In-memory stand-in for CacheService (get/set + key helper)."""

    def __init__(self) -> None:
        self.store: dict = {}

    @staticmethod
    def ai_response_key(signature: str) -> str:
        return f"ai:resp:{signature}"

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl=900):
        self.store[key] = value


class FakeBudget:
    """Injectable budget that records calls and can fail closed on check()."""

    def __init__(self, raise_on_check: bool = False) -> None:
        self.raise_on_check = raise_on_check
        self.checked: list = []
        self.recorded: list = []

    async def check(self, user_id):
        self.checked.append(user_id)
        if self.raise_on_check:
            raise BudgetExceededError(used=999, limit=100)

    async def record(self, user_id, tokens):
        self.recorded.append((user_id, tokens))


class FakeRedis:
    """Minimal async Redis for AITokenBudget (get/incrby/expire)."""

    def __init__(self) -> None:
        self.store: dict = {}
        self.expiries: dict = {}

    async def get(self, key):
        return self.store.get(key)

    async def incrby(self, key, amount):
        self.store[key] = int(self.store.get(key, 0)) + amount
        return self.store[key]

    async def expire(self, key, ttl):
        self.expiries[key] = ttl


def _fake_anthropic(text: str = "ANALYSIS RESULT", in_tok: int = 10, out_tok: int = 20):
    message = MagicMock()
    message.content = [MagicMock(text=text)]
    message.usage = MagicMock(input_tokens=in_tok, output_tokens=out_tok)
    client = MagicMock()
    client.messages.create.return_value = message
    return client


def _make_service(cache, budget):
    """AIService with mocked DB/settings so analyze() runs offline."""
    svc = AIService(MagicMock(), user_id=uuid.uuid4(), cache=cache, budget=budget)
    svc.get_api_key = AsyncMock(return_value="sk-test")
    svc.get_settings = AsyncMock(
        return_value=AISettingsResponse(
            has_api_key=True, default_model="claude-sonnet-5", custom_instructions=None
        )
    )
    svc._build_prompt_and_context = AsyncMock(return_value=("PROMPT", "CTX"))
    return svc


# ---------------------------------------------------------------------------
# 1. Model ids + configurable default
# ---------------------------------------------------------------------------
def test_ai_model_ids_are_current():
    values = {m.value for m in AIModel}
    assert values == {
        "claude-sonnet-5",
        "claude-opus-4-8",
        "claude-haiku-4-5-20251001",
    }
    assert AIModel.CLAUDE_SONNET.value == "claude-sonnet-5"
    # No retired 3.5 ids remain anywhere in the enum.
    assert not any("claude-3-5" in v for v in values)


def test_resolve_model_default_is_configurable(monkeypatch):
    svc = AIService(MagicMock())
    req = AIAnalysisRequest(analysis_type=AnalysisType.GENERAL, prompt="x")  # model omitted
    monkeypatch.setattr(settings, "AI_DEFAULT_MODEL", "claude-opus-4-8")
    assert svc._resolve_model(req) == AIModel.CLAUDE_OPUS
    monkeypatch.setattr(settings, "AI_DEFAULT_MODEL", "claude-haiku-4-5-20251001")
    assert svc._resolve_model(req) == AIModel.CLAUDE_HAIKU


def test_resolve_model_explicit_request_wins(monkeypatch):
    svc = AIService(MagicMock())
    monkeypatch.setattr(settings, "AI_DEFAULT_MODEL", "claude-sonnet-5")
    req = AIAnalysisRequest(
        analysis_type=AnalysisType.GENERAL, prompt="x", model=AIModel.CLAUDE_OPUS
    )
    assert svc._resolve_model(req) == AIModel.CLAUDE_OPUS


def test_resolve_model_skips_retired_id(monkeypatch):
    """A stored default that is a retired id is ignored, never sent to the API."""
    svc = AIService(MagicMock())
    monkeypatch.setattr(settings, "AI_DEFAULT_MODEL", "claude-sonnet-5")
    resolved = svc._resolve_model(req_general(), default_model="claude-3-5-sonnet-20241022")
    assert resolved == AIModel.CLAUDE_SONNET
    assert resolved.value == "claude-sonnet-5"


def req_general() -> AIAnalysisRequest:
    return AIAnalysisRequest(analysis_type=AnalysisType.GENERAL, prompt="x")


# ---------------------------------------------------------------------------
# 2. Key split-brain — read via the encrypted accessor
# ---------------------------------------------------------------------------
async def test_get_api_key_uses_encrypted_accessor():
    db = MagicMock()
    # If the old code path (direct UserSetting read, no decrypt) were used it
    # would call db.execute — assert it never does.
    db.execute = AsyncMock(side_effect=AssertionError("must not bypass SettingsService"))
    svc = AIService(db, user_id=uuid.uuid4())
    svc._settings_service.get_setting = AsyncMock(return_value="sk-decrypted")

    key = await svc.get_api_key()

    assert key == "sk-decrypted"
    svc._settings_service.get_setting.assert_awaited_once_with(
        SettingsService.CLAUDE_API_KEY, svc.user_id
    )


async def test_get_api_key_falls_back_to_env(monkeypatch):
    svc = AIService(MagicMock())
    svc._settings_service.get_setting = AsyncMock(return_value=None)
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "env-key")
    assert await svc.get_api_key() == "env-key"


# ---------------------------------------------------------------------------
# 3. WATCHLIST / GENERAL — DECISION: implemented (not removed)
# ---------------------------------------------------------------------------
def test_watchlist_and_general_types_retained():
    assert AnalysisType.WATCHLIST.value == "watchlist"
    assert AnalysisType.GENERAL.value == "general"


async def test_watchlist_branch_builds_context():
    svc = AIService(MagicMock(), user_id=uuid.uuid4())
    ctx = WatchlistContext(
        name="Uranium",
        description="miners",
        holdings=[
            WatchlistHolding(
                symbol="CCJ",
                name="Cameco",
                price=50.0,
                change_percent=1.2,
                target_price=60.0,
                thesis="supply squeeze",
            )
        ],
    )
    svc._get_watchlist_context = AsyncMock(return_value=ctx)
    req = AIAnalysisRequest(
        analysis_type=AnalysisType.WATCHLIST, prompt="assess", watchlist_id=4
    )

    prompt, summary = await svc._build_prompt_and_context(req)

    assert "CCJ" in prompt and "Uranium" in prompt and "supply squeeze" in prompt
    assert summary == "Watchlist: Uranium (1)"


async def test_general_is_handled_context_less():
    svc = AIService(MagicMock())
    req = AIAnalysisRequest(analysis_type=AnalysisType.GENERAL, prompt="What is the VIX?")
    prompt, summary = await svc._build_prompt_and_context(req)
    assert prompt == "What is the VIX?"  # raw prompt, no context
    assert summary is None


# ---------------------------------------------------------------------------
# 4a. Redis response cache — hit on repeat
# ---------------------------------------------------------------------------
async def test_response_cache_hits_on_repeat():
    cache, budget = FakeCache(), FakeBudget()
    svc = _make_service(cache, budget)
    client = _fake_anthropic()
    req = AIAnalysisRequest(analysis_type=AnalysisType.GENERAL, prompt="hi")

    with patch("anthropic.Anthropic", return_value=client):
        first = await svc.analyze(req)
        second = await svc.analyze(req)

    assert client.messages.create.call_count == 1  # second served from cache
    assert first.cached is False
    assert second.cached is True
    assert second.response == "ANALYSIS RESULT"
    # Budget consumed exactly once (cache hit spends nothing).
    assert budget.recorded == [(svc.user_id, 30)]


# ---------------------------------------------------------------------------
# 4b. Per-day token budget — fails closed
# ---------------------------------------------------------------------------
async def test_analyze_fails_closed_when_budget_exceeded():
    budget = FakeBudget(raise_on_check=True)
    svc = _make_service(FakeCache(), budget)
    req = AIAnalysisRequest(analysis_type=AnalysisType.GENERAL, prompt="hi")

    with patch("anthropic.Anthropic") as ctor:
        with pytest.raises(BudgetExceededError):
            await svc.analyze(req)
        ctor.assert_not_called()  # blocked before any API/token spend


async def test_token_budget_ceiling(monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_TOKEN_BUDGET", 100)
    budget = AITokenBudget(redis_client=FakeRedis())
    uid = uuid.uuid4()

    await budget.check(uid)  # 0 used → ok
    await budget.record(uid, 60)
    assert await budget.used(uid) == 60
    await budget.check(uid)  # 60 < 100 → ok

    await budget.record(uid, 50)  # now 110 ≥ 100
    with pytest.raises(BudgetExceededError):
        await budget.check(uid)


async def test_token_budget_disabled_when_zero(monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_TOKEN_BUDGET", 0)
    budget = AITokenBudget(redis_client=FakeRedis())
    uid = uuid.uuid4()
    await budget.check(uid)  # never raises
    await budget.record(uid, 10_000_000)
    assert await budget.used(uid) == 0


def test_usage_tokens_sums_input_and_output():
    msg = MagicMock()
    msg.usage = MagicMock(input_tokens=7, output_tokens=13)
    assert _usage_tokens(msg) == 20
    no_usage = MagicMock()
    no_usage.usage = None
    assert _usage_tokens(no_usage) == 0


# ---------------------------------------------------------------------------
# 5. SSE framing — valid data: …\n\n events
# ---------------------------------------------------------------------------
def test_format_sse_single_line():
    assert format_sse("Hello") == "data: Hello\n\n"


def test_format_sse_multiline_is_valid():
    out = format_sse("Hello\nWorld")
    assert out == "data: Hello\ndata: World\n\n"
    # Terminated by a blank line; no bare (non-data) content lines.
    assert out.endswith("\n\n")
    for line in out.split("\n")[:-2]:
        assert line.startswith("data:")


def test_format_sse_fixes_old_bare_line_bug():
    chunk = "Line1\nLine2"
    old_framing = f"data: {chunk}\n\n"  # the previous, malformed framing
    # Old framing leaked a bare 'Line2' with no data: prefix (spec violation).
    assert any(ln and not ln.startswith("data:") for ln in old_framing.split("\n"))
    # New framing has no bare content lines.
    new_framing = format_sse(chunk)
    assert all(ln == "" or ln.startswith("data:") for ln in new_framing.split("\n"))


def test_format_sse_done_marker():
    assert format_sse("[DONE]") == "data: [DONE]\n\n"
