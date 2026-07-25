"""``_select_scoring_candidates`` must return NewsItem rows deterministically
when two rows share ONE ``published_at`` (AB3).

``_select_scoring_candidates`` (news_catalyst.py) built its query with
``.order_by(NewsItem.published_at.desc())`` alone. Two unscored ``NewsItem``
rows that share an identical ``published_at`` (e.g. two articles ingested in
the same provider batch/second) then sort in whatever order Postgres happens
to return for the tie, which SQL does not guarantee to be insertion order -
so an otherwise-unchanged rerun could hand the LLM scoring batch a different
article order.

This is a DISPLAY/NARRATIVE-ORDER determinism fix only, NOT a
financial-calculation fix: the candidates feed a relevance/summary scoring
pass over each article's own metadata, not any trade/position figure. It
does not change WHICH rows are eventually scored either - a row that misses
this run's cap is automatically retried on a later run (see the module
docstring on ``_select_scoring_candidates``) - only the order is now
deterministic.

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
from app.services.agents.news_catalyst import MAX_ARTICLES_SCORED_PER_RUN, NewsCatalystAgent


class TestSelectScoringCandidatesTiebreak:
    async def test_tied_published_at_resolves_id_descending_stably(self, db: AsyncSession):
        """Two unscored news rows share one ``published_at``; the query must
        return them id-descending - not whichever order the DB happens to
        return for the tie - and the same way on every repeated call.
        """
        shared_published_at = datetime.now(timezone.utc) - timedelta(hours=1)

        # Insert the LOWER id first (physically first), then the HIGHER id
        # second (physically last) - decouples physical/insertion order from
        # numeric id order so the missing tiebreak is exercised for real,
        # not just in theory.
        row_low = NewsItem(
            id=820001,
            symbol="TIEC",
            headline="First inserted, lower id",
            url="https://example.com/ab3-news-catalyst-tie-low",
            source="AP",
            published_at=shared_published_at,
            relevance=None,
        )
        db.add(row_low)
        await db.commit()

        row_high = NewsItem(
            id=820002,
            symbol="TIED",
            headline="Second inserted, higher id",
            url="https://example.com/ab3-news-catalyst-tie-high",
            source="AP",
            published_at=shared_published_at,
            relevance=None,
        )
        db.add(row_high)
        await db.commit()

        assert row_high.id > row_low.id, "test setup: row_high must have the higher id"

        agent = NewsCatalystAgent()

        # Stable across 5 repeated calls, not just lucky once.
        for _ in range(5):
            candidates = await agent._select_scoring_candidates(db)
            ids = [c.id for c in candidates if c.id in (row_low.id, row_high.id)]
            assert ids == [row_high.id, row_low.id], (
                "must return id-descending regardless of physical insertion "
                f"order or a same-timestamp tie; got {ids}"
            )


class TestSelectScoringCandidatesCapBoundary:
    """Cap-boundary extension of AB3/#232's 2-row tie test (AC6).

    #232 proved the tiebreak orders two tied rows deterministically. It did
    not prove what happens when MORE tied rows exist than
    ``MAX_ARTICLES_SCORED_PER_RUN`` (the ``.limit(50)`` on the query) admits:
    does the cap keep an arbitrary 50-of-N, or specifically the id-descending
    PREFIX of the tie set - i.e. does the tiebreak still hold exactly at the
    boundary where SQL gets to decide which rows are in vs. out, not just
    their order?
    """

    async def test_cap_boundary_selects_id_descending_prefix_stably(self, db: AsyncSession):
        """More unscored rows share one ``published_at`` than the cap admits:
        the query must return exactly the id-descending PREFIX of the tie
        set (the highest-id rows), excluding the lowest-id rows entirely -
        not an arbitrary N-of-M subset - and the same way on every repeated
        call.

        Physical insertion order below is id-ASCENDING (lowest id first,
        highest id last), so the correct retained subset - id-descending,
        highest ids first - is the REVERSE of insertion order for those
        rows, and the excluded rows are exactly the ones inserted first.
        Matching physical/insertion order by coincidence, or returning any
        50-of-53, would fail this.
        """
        base_id = 822_000
        tie_count = MAX_ARTICLES_SCORED_PER_RUN + 3
        shared_published_at = datetime.now(timezone.utc) - timedelta(hours=1)

        all_ids = [base_id + i for i in range(tie_count)]
        for news_id in all_ids:
            db.add(
                NewsItem(
                    id=news_id,
                    symbol="TIEN",
                    headline=f"Cap-boundary tie candidate {news_id}",
                    url=f"https://example.com/ab3-cap-boundary-news-catalyst-{news_id}",
                    source="AP",
                    published_at=shared_published_at,
                    relevance=None,
                )
            )
        await db.commit()

        expected_selected = sorted(all_ids, reverse=True)[:MAX_ARTICLES_SCORED_PER_RUN]
        expected_excluded = set(all_ids) - set(expected_selected)
        assert len(expected_excluded) == 3, "test setup: exactly 3 rows must fall outside the cap"

        agent = NewsCatalystAgent()

        # Stable across 5 repeated calls, not just lucky once.
        for _ in range(5):
            candidates = await agent._select_scoring_candidates(db)
            candidate_ids = [c.id for c in candidates if c.id in all_ids]
            assert len(candidate_ids) == MAX_ARTICLES_SCORED_PER_RUN, (
                f"cap must admit exactly {MAX_ARTICLES_SCORED_PER_RUN} rows "
                f"from the {tie_count}-row tie set; got {len(candidate_ids)}"
            )
            assert candidate_ids == expected_selected, (
                "cap must select the id-descending PREFIX of the tie set "
                f"(the {MAX_ARTICLES_SCORED_PER_RUN} highest ids), not an "
                f"arbitrary subset; got {candidate_ids}"
            )
            assert expected_excluded.isdisjoint(candidate_ids), (
                "rows outside the id-descending cap prefix must never be "
                f"selected; found {expected_excluded & set(candidate_ids)}"
            )
