"""Tests for the News & Catalyst advisory agent (T1 sub-PR 2/4).

Covers: fetch/parse helpers (pure, no I/O), persist dedup (in-batch + against
an existing row), retention pruning, watchlist symbol collection, the
Finnhub-unconfigured no-op, the per-run symbol cap, and LLM scoring (success,
call failure, malformed response, no-api-key, and the per-run article cap).
Finnhub and the Anthropic client are always faked/mocked - no live I/O. DB
tests use the ``db`` fixture (live Postgres, rolled back per test).
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select

from app.db.models.news_item import NewsItem
from app.schemas.ai import AISettingsResponse
from app.services.agents.news_catalyst import (
    MAX_ARTICLES_SCORED_PER_RUN,
    MAX_SYMBOLS_PER_RUN,
    NewsCatalystAgent,
    _parse_finnhub_timestamp,
    _parse_scoring_response,
    _resolve_scoring_model,
)
from app.services.agents.news_catalyst import token_budget as news_token_budget
from app.services.ai import AIService
from tests.factories import (
    create_test_equity,
    create_test_watchlist,
    create_test_watchlist_item,
)


class FakeFinnhubProvider:
    """Injectable double for FinnhubNewsProvider - no live HTTP."""

    def __init__(self, configured=True, company_news=None, market_news=None):
        self._configured = configured
        self.company_news = company_news or {}
        self.market_news_items = market_news or []
        self.company_calls: list[str] = []
        self.market_calls = 0

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def get_company_news(self, symbol: str, days_back: int = 3):
        self.company_calls.append(symbol)
        return self.company_news.get(symbol, [])

    async def get_market_news(self, category: str = "general"):
        self.market_calls += 1
        return self.market_news_items


def _raw(headline="Headline", url="https://example.com/a", source="Reuters", ts=None, summary=None):
    if ts is None:
        ts = int(datetime.now(timezone.utc).timestamp())
    return {"headline": headline, "url": url, "source": source, "datetime": ts, "summary": summary}


def _fake_anthropic_client(text: str, in_tok: int = 50, out_tok: int = 80):
    message = MagicMock()
    message.content = [MagicMock(text=text)]
    message.usage = MagicMock(input_tokens=in_tok, output_tokens=out_tok)
    client = MagicMock()
    client.messages.create.return_value = message
    return client


def _mock_ai_service(monkeypatch, api_key="sk-live", default_model="claude-sonnet-5"):
    monkeypatch.setattr(AIService, "get_api_key", AsyncMock(return_value=api_key))
    monkeypatch.setattr(
        AIService,
        "get_settings",
        AsyncMock(
            return_value=AISettingsResponse(
                has_api_key=bool(api_key), default_model=default_model, custom_instructions=None
            )
        ),
    )


async def _make_items(db, n=2, symbol="UUUU") -> list[NewsItem]:
    items = []
    for i in range(n):
        item = NewsItem(
            symbol=symbol,
            headline=f"Headline {i}",
            url=f"https://example.com/item-{i}",
            source="Reuters",
            published_at=datetime.now(timezone.utc),
        )
        db.add(item)
        items.append(item)
    await db.flush()
    return items


# ---------------------------------------------------------------------------
# Pure helpers - no DB, no I/O
# ---------------------------------------------------------------------------
def test_parse_finnhub_timestamp_produces_tz_aware_utc():
    result = _parse_finnhub_timestamp(1752831600)
    assert result is not None
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)


@pytest.mark.parametrize("bad", [None, "not-a-number", 0, -5, "", []])
def test_parse_finnhub_timestamp_rejects_malformed(bad):
    assert _parse_finnhub_timestamp(bad) is None


def test_resolve_scoring_model_prefers_valid_candidate(monkeypatch):
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "AI_DEFAULT_MODEL", "claude-sonnet-5")
    assert _resolve_scoring_model("claude-opus-4-8") == "claude-opus-4-8"


def test_resolve_scoring_model_skips_unknown_id_and_falls_back(monkeypatch):
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "AI_DEFAULT_MODEL", "claude-sonnet-5")
    assert _resolve_scoring_model("not-a-real-model") == "claude-sonnet-5"


def test_resolve_scoring_model_none_falls_back_to_app_default(monkeypatch):
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "AI_DEFAULT_MODEL", "claude-haiku-4-5-20251001")
    assert _resolve_scoring_model(None) == "claude-haiku-4-5-20251001"


def test_parse_scoring_response_valid_json():
    text = json.dumps(
        [
            {"index": 0, "relevance": 0.9, "summary": "Big catalyst"},
            {"index": 1, "relevance": 1.5, "summary": "Clamped to 1.0"},
        ]
    )
    parsed = _parse_scoring_response(text, count=2)
    assert parsed[0] == (0.9, "Big catalyst")
    assert parsed[1][0] == 1.0


def test_parse_scoring_response_handles_code_fence():
    text = '```json\n[{"index": 0, "relevance": 0.5, "summary": "x"}]\n```'
    parsed = _parse_scoring_response(text, count=1)
    assert parsed[0] == (0.5, "x")


def test_parse_scoring_response_malformed_json_returns_empty():
    assert _parse_scoring_response("not json at all", count=3) == {}


def test_parse_scoring_response_not_a_list_returns_empty():
    assert _parse_scoring_response('{"index": 0}', count=1) == {}


def test_parse_scoring_response_out_of_range_index_dropped():
    text = json.dumps([{"index": 5, "relevance": 0.5, "summary": "x"}])
    assert _parse_scoring_response(text, count=2) == {}


def test_parse_scoring_response_empty_string_returns_empty():
    assert _parse_scoring_response("", count=2) == {}


# ---------------------------------------------------------------------------
# Retention prune
# ---------------------------------------------------------------------------
async def test_prune_old_news_deletes_stale_keeps_recent(db):
    old = NewsItem(
        headline="Old",
        url="https://example.com/old",
        source="Reuters",
        published_at=datetime.now(timezone.utc) - timedelta(days=45),
    )
    recent = NewsItem(
        headline="Recent",
        url="https://example.com/recent",
        source="Reuters",
        published_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db.add_all([old, recent])
    await db.flush()

    agent = NewsCatalystAgent()
    pruned = await agent.prune_old_news(db)

    assert pruned == 1
    remaining = (await db.execute(select(NewsItem.url))).scalars().all()
    assert remaining == ["https://example.com/recent"]


# ---------------------------------------------------------------------------
# Watchlist symbol collection
# ---------------------------------------------------------------------------
async def test_watchlist_symbols_dedup_across_watchlists(db):
    eq_a = await create_test_equity(db, symbol="UUUU")
    eq_b = await create_test_equity(db, symbol="CCJ")
    wl1 = await create_test_watchlist(db, name="WL1")
    wl2 = await create_test_watchlist(db, name="WL2")
    await create_test_watchlist_item(db, wl1, eq_a)
    await create_test_watchlist_item(db, wl1, eq_b)
    await create_test_watchlist_item(db, wl2, eq_a)  # same symbol, second watchlist

    agent = NewsCatalystAgent()
    symbols = await agent._watchlist_symbols(db)

    assert symbols.count("UUUU") == 1
    assert set(symbols) == {"UUUU", "CCJ"}


# ---------------------------------------------------------------------------
# Persist / dedup
# ---------------------------------------------------------------------------
async def test_persist_dedups_within_batch_and_against_existing_row(db):
    db.add(
        NewsItem(
            headline="Existing",
            url="https://example.com/dupe",
            source="AP",
            published_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()

    now = datetime.now(timezone.utc)
    parsed = [
        {
            "symbol": "UUUU",
            "headline": "Already stored",
            "url": "https://example.com/dupe",
            "source": "Reuters",
            "published_at": now,
            "summary": None,
        },
        {
            "symbol": "UUUU",
            "headline": "Genuinely new",
            "url": "https://example.com/new",
            "source": "Reuters",
            "published_at": now,
            "summary": None,
        },
        {
            "symbol": "CCJ",
            "headline": "Same url, second symbol's fetch",
            "url": "https://example.com/new",
            "source": "Reuters",
            "published_at": now,
            "summary": None,
        },
    ]

    agent = NewsCatalystAgent()
    new_rows = await agent._persist(db, parsed)

    assert len(new_rows) == 1
    assert new_rows[0].url == "https://example.com/new"
    all_urls = (await db.execute(select(NewsItem.url))).scalars().all()
    assert sorted(all_urls) == ["https://example.com/dupe", "https://example.com/new"]


async def test_persist_empty_input_is_a_noop(db):
    agent = NewsCatalystAgent()
    assert await agent._persist(db, []) == []


# ---------------------------------------------------------------------------
# execute() - fetch orchestration
# ---------------------------------------------------------------------------
async def test_execute_noop_when_finnhub_unconfigured(db):
    provider = FakeFinnhubProvider(configured=False)
    agent = NewsCatalystAgent(provider=provider)

    await agent.execute(db, uuid.uuid4())

    assert provider.company_calls == []
    assert provider.market_calls == 0
    count = await db.scalar(select(func.count()).select_from(NewsItem))
    assert count == 0


async def test_execute_caps_symbols_at_configured_max(db):
    equities = [
        await create_test_equity(db, symbol=f"SYM{i}") for i in range(MAX_SYMBOLS_PER_RUN + 5)
    ]
    wl = await create_test_watchlist(db, name="Big Watchlist")
    for eq in equities:
        await create_test_watchlist_item(db, wl, eq)

    provider = FakeFinnhubProvider(configured=True)
    agent = NewsCatalystAgent(provider=provider)
    agent._throttle = AsyncMock()  # skip real sleeps in the test

    await agent.execute(db, uuid.uuid4())

    assert len(provider.company_calls) == MAX_SYMBOLS_PER_RUN
    assert provider.market_calls == 1


async def test_execute_persists_parsed_items_and_scores_them(db, monkeypatch):
    eq = await create_test_equity(db, symbol="UUUU")
    wl = await create_test_watchlist(db, name="WL")
    await create_test_watchlist_item(db, wl, eq)

    provider = FakeFinnhubProvider(
        configured=True,
        company_news={
            "UUUU": [_raw(headline="DOE reserve program", url="https://example.com/uuuu-1")]
        },
        market_news=[_raw(headline="Fed holds rates", url="https://example.com/market-1")],
    )
    agent = NewsCatalystAgent(provider=provider)
    agent._throttle = AsyncMock()

    _mock_ai_service(monkeypatch)
    response_text = json.dumps(
        [
            {"index": 0, "relevance": 0.9, "summary": "DOE catalyst"},
            {"index": 1, "relevance": 0.05, "summary": "Routine"},
        ]
    )
    client = _fake_anthropic_client(response_text)

    with patch("anthropic.Anthropic", return_value=client):
        await agent.execute(db, uuid.uuid4())

    rows = (await db.execute(select(NewsItem).order_by(NewsItem.id))).scalars().all()
    assert {r.url for r in rows} == {
        "https://example.com/uuuu-1",
        "https://example.com/market-1",
    }
    by_url = {r.url: r for r in rows}
    assert by_url["https://example.com/uuuu-1"].symbol == "UUUU"
    assert by_url["https://example.com/market-1"].symbol is None
    # Both items were scored (order between the two fetch calls determines
    # which prompt index each got - both are new, so both must be non-null).
    assert all(r.relevance is not None for r in rows)


# ---------------------------------------------------------------------------
# _score() - LLM scoring behavior
# ---------------------------------------------------------------------------
async def test_score_success_sets_relevance_and_summary_and_records_budget(db, monkeypatch):
    items = await _make_items(db, 2)
    uid = uuid.uuid4()
    _mock_ai_service(monkeypatch)

    response_text = json.dumps(
        [
            {"index": 0, "relevance": 0.92, "summary": "DOE announced new uranium reserve program."},
            {"index": 1, "relevance": 0.1, "summary": "Minor mention."},
        ]
    )
    client = _fake_anthropic_client(response_text, in_tok=50, out_tok=80)

    recorded: list[tuple] = []

    async def fake_record(user_id, tokens):
        recorded.append((user_id, tokens))

    monkeypatch.setattr(news_token_budget, "record", fake_record)

    with patch("anthropic.Anthropic", return_value=client):
        agent = NewsCatalystAgent()
        await agent._score(db, uid, items)

    assert items[0].relevance == pytest.approx(0.92)
    assert items[0].summary == "DOE announced new uranium reserve program."
    assert items[1].relevance == pytest.approx(0.1)
    assert recorded == [(uid, 130)]


async def test_score_no_api_key_leaves_items_unscored(db, monkeypatch):
    items = await _make_items(db, 1)
    monkeypatch.setattr(AIService, "get_api_key", AsyncMock(return_value=None))

    agent = NewsCatalystAgent()
    await agent._score(db, uuid.uuid4(), items)

    assert items[0].relevance is None


async def test_score_llm_call_failure_leaves_items_unscored(db, monkeypatch):
    items = await _make_items(db, 1)
    _mock_ai_service(monkeypatch)

    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("upstream boom")

    with patch("anthropic.Anthropic", return_value=client):
        agent = NewsCatalystAgent()
        await agent._score(db, uuid.uuid4(), items)

    assert items[0].relevance is None
    await db.refresh(items[0])
    assert items[0].relevance is None  # persisted, still unscored


async def test_score_malformed_response_leaves_items_unscored(db, monkeypatch):
    items = await _make_items(db, 1)
    _mock_ai_service(monkeypatch)

    client = _fake_anthropic_client("not valid json at all")

    with patch("anthropic.Anthropic", return_value=client):
        agent = NewsCatalystAgent()
        await agent._score(db, uuid.uuid4(), items)

    assert items[0].relevance is None


async def test_score_caps_articles_scored_per_run(db, monkeypatch):
    items = await _make_items(db, MAX_ARTICLES_SCORED_PER_RUN + 3)
    _mock_ai_service(monkeypatch)

    response_text = json.dumps(
        [
            {"index": i, "relevance": 0.5, "summary": "x"}
            for i in range(MAX_ARTICLES_SCORED_PER_RUN)
        ]
    )
    client = _fake_anthropic_client(response_text)

    with patch("anthropic.Anthropic", return_value=client):
        agent = NewsCatalystAgent()
        await agent._score(db, uuid.uuid4(), items)

    assert client.messages.create.call_count == 1
    scored = [i for i in items if i.relevance is not None]
    assert len(scored) == MAX_ARTICLES_SCORED_PER_RUN
    # The overflow items (beyond the cap) are untouched, not scored.
    assert all(i.relevance is None for i in items[MAX_ARTICLES_SCORED_PER_RUN:])
