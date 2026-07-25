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
from app.services.agents.strategy_brief import NEWS_LIMIT, _collect_news


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


class TestCollectNewsCapBoundary:
    """Cap-boundary extension of AB3/#232's 2-row tie test (AC6).

    #232 proved the tiebreak orders two tied rows deterministically. It did
    not prove what happens when MORE tied rows exist than ``NEWS_LIMIT``
    (the ``.limit(NEWS_LIMIT)`` on the query) admits: does the cap keep an
    arbitrary N-of-M, or specifically the id-descending PREFIX of the tie
    set - i.e. does the tiebreak still hold exactly at the boundary where
    SQL gets to decide which rows are in vs. out, not just their order?
    """

    async def test_cap_boundary_selects_id_descending_prefix_stably(self, db: AsyncSession):
        """More rows share one ``published_at`` than the cap admits: the
        query must return exactly the id-descending PREFIX of the tie set
        (the highest-id rows), excluding the lowest-id rows entirely - not
        an arbitrary N-of-M subset - and the same way on every repeated
        call.

        Physical insertion order below is id-ASCENDING (lowest id first,
        highest id last), so the correct retained subset - id-descending,
        highest ids first - is the REVERSE of insertion order for those
        rows, and the excluded rows are exactly the ones inserted first.
        Matching physical/insertion order by coincidence, or returning any
        N-of-M, would fail this.
        """
        base_id = 812_000
        tie_count = NEWS_LIMIT + 3
        shared_published_at = datetime.now(timezone.utc) - timedelta(hours=1)

        all_ids = [base_id + i for i in range(tie_count)]
        id_to_url = {
            news_id: f"https://example.com/ab3-cap-boundary-strategy-brief-{news_id}"
            for news_id in all_ids
        }
        for news_id in all_ids:
            db.add(
                NewsItem(
                    id=news_id,
                    symbol="TIES",
                    headline=f"Cap-boundary tie candidate {news_id}",
                    url=id_to_url[news_id],
                    source="AP",
                    published_at=shared_published_at,
                )
            )
        await db.commit()

        expected_selected_ids = sorted(all_ids, reverse=True)[:NEWS_LIMIT]
        expected_selected_urls = [id_to_url[news_id] for news_id in expected_selected_ids]
        expected_excluded_urls = {id_to_url[news_id] for news_id in all_ids} - set(
            expected_selected_urls
        )
        assert len(expected_excluded_urls) == 3, "test setup: exactly 3 rows must fall outside the cap"

        # Stable across 5 repeated calls, not just lucky once.
        for _ in range(5):
            news = await _collect_news(db)
            urls = [n["url"] for n in news if n["symbol"] == "TIES"]
            assert len(urls) == NEWS_LIMIT, (
                f"cap must admit exactly {NEWS_LIMIT} rows from the "
                f"{tie_count}-row tie set; got {len(urls)}"
            )
            assert urls == expected_selected_urls, (
                "cap must select the id-descending PREFIX of the tie set "
                f"(the {NEWS_LIMIT} highest ids), not an arbitrary subset; "
                f"got {urls}"
            )
            assert expected_excluded_urls.isdisjoint(urls), (
                "rows outside the id-descending cap prefix must never be "
                f"selected; found {expected_excluded_urls & set(urls)}"
            )
