"""``_collect_news`` must return NewsItem rows deterministically when two rows
share ONE ``published_at`` (AB3).

``_collect_news`` (strategy_brief.py) built its query with
``.order_by(NewsItem.published_at.desc())`` alone. Two ``NewsItem`` rows that
share an identical ``published_at`` (e.g. two articles ingested in the same
provider batch/second) then sort in whatever order Postgres happens to
return for the tie, which SQL does not guarantee to be insertion order - so
an otherwise-unchanged rerun could hand the LLM narrative prompt a different
headline order.

This is a DISPLAY/NARRATIVE-ORDER determinism fix only, NOT a
financial-calculation fix: ``_collect_news`` only feeds the strategy brief's
LLM context dict, it does not compute or persist any trade/position figures.

Modeled on ``tests/test_services/test_trade_journal_pair_order.py`` (AA5,
PR #230), which fixed the sibling non-determinism in
``_closed_trade_pairs``. As there, the fix adds the primary-key column as a
secondary sort key: ``.order_by(NewsItem.published_at.desc(),
NewsItem.id.desc())`` - descending to match the primary (`.desc()`) key,
so ties resolve newest-id-first - guaranteed by SQL semantics to break the
tie the same way every time, regardless of physical row layout.

To make the missing tiebreak concretely observable (not just theoretically
possible), the two ``NewsItem`` rows below are given explicit ids reversed
from their physical insertion order: the row inserted FIRST gets the LOWER
id, and the row inserted SECOND gets the HIGHER id - so the correct
(id-descending) result order is the reverse of insertion order, not an
accidental match to it.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.news_item import NewsItem
from app.services.agents.strategy_brief import _collect_news


class TestCollectNewsTiebreak:
    async def test_tied_published_at_resolves_id_descending_stably(self, db: AsyncSession):
        """Two news rows share one ``published_at``; the query must return
        them id-descending - not whichever order the DB happens to return
        for the tie - and the same way on every repeated call.
        """
        shared_published_at = datetime.now(timezone.utc) - timedelta(hours=1)

        # Insert the LOWER id first (physically first), then the HIGHER id
        # second (physically last) - decouples physical/insertion order from
        # numeric id order so the missing tiebreak is exercised for real,
        # not just in theory.
        row_low = NewsItem(
            id=810001,
            symbol="TIEA",
            headline="First inserted, lower id",
            url="https://example.com/ab3-strategy-brief-tie-low",
            source="AP",
            published_at=shared_published_at,
        )
        db.add(row_low)
        await db.commit()

        row_high = NewsItem(
            id=810002,
            symbol="TIEB",
            headline="Second inserted, higher id",
            url="https://example.com/ab3-strategy-brief-tie-high",
            source="AP",
            published_at=shared_published_at,
        )
        db.add(row_high)
        await db.commit()

        assert row_high.id > row_low.id, "test setup: row_high must have the higher id"

        # Stable across 5 repeated calls, not just lucky once.
        for _ in range(5):
            news = await _collect_news(db)
            urls = [n["url"] for n in news if n["symbol"] in ("TIEA", "TIEB")]
            assert urls == [row_high.url, row_low.url], (
                "must return id-descending regardless of physical insertion "
                f"order or a same-timestamp tie; got {urls}"
            )
