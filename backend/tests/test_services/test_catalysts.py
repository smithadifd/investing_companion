"""Tests for app.services.catalysts (morning-pulse catalyst line selection).

Selection is deterministic (docs/issues/014 T1 sub-PR 2/4, binding addendum
#6): relevance >= 0.70, one row per symbol (highest relevance, then newest,
then highest id), within the last 36 hours, text = summary-else-headline,
whitespace-normalized, truncated to 80 chars including the ellipsis.
"""

from datetime import datetime, timedelta, timezone

from app.db.models.news_item import NewsItem
from app.services.catalysts import (
    CATALYST_LINE_MAX_CHARS,
    _condense,
    _truncate_catalyst,
    get_catalyst_lines,
)


def test_condense_collapses_whitespace():
    assert _condense("Line one\n  line   two\t\ttab") == "Line one line two tab"


def test_condense_handles_none_and_empty():
    assert _condense(None) == ""
    assert _condense("") == ""


def test_truncate_catalyst_short_text_unchanged():
    assert _truncate_catalyst("Short catalyst.") == "Short catalyst."


def test_truncate_catalyst_cuts_with_ellipsis_at_max_chars():
    text = "x" * 100
    result = _truncate_catalyst(text)
    assert len(result) == CATALYST_LINE_MAX_CHARS
    assert result.endswith("…")


def test_truncate_catalyst_condenses_before_truncating():
    text = "line one\nline two\nline three " * 5
    result = _truncate_catalyst(text)
    assert "\n" not in result
    assert len(result) <= CATALYST_LINE_MAX_CHARS


async def test_get_catalyst_lines_empty_symbols_returns_empty(db):
    assert await get_catalyst_lines(db, []) == {}


async def test_get_catalyst_lines_filters_below_relevance_bar(db):
    db.add(
        NewsItem(
            symbol="UUUU",
            headline="Low relevance",
            url="https://example.com/low",
            source="AP",
            published_at=datetime.now(timezone.utc),
            relevance=0.5,
        )
    )
    await db.flush()

    assert await get_catalyst_lines(db, ["UUUU"]) == {}


async def test_get_catalyst_lines_filters_unscored_rows(db):
    db.add(
        NewsItem(
            symbol="UUUU",
            headline="Unscored",
            url="https://example.com/unscored",
            source="AP",
            published_at=datetime.now(timezone.utc),
            relevance=None,
        )
    )
    await db.flush()

    assert await get_catalyst_lines(db, ["UUUU"]) == {}


async def test_get_catalyst_lines_filters_outside_lookback_window(db):
    db.add(
        NewsItem(
            symbol="UUUU",
            headline="Stale catalyst",
            url="https://example.com/stale",
            source="AP",
            published_at=datetime.now(timezone.utc) - timedelta(hours=48),
            relevance=0.9,
        )
    )
    await db.flush()

    assert await get_catalyst_lines(db, ["UUUU"]) == {}


async def test_get_catalyst_lines_picks_highest_relevance_per_symbol(db):
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            NewsItem(
                symbol="UUUU",
                headline="Lower",
                url="https://example.com/a",
                source="AP",
                published_at=now,
                relevance=0.75,
                summary=None,
            ),
            NewsItem(
                symbol="UUUU",
                headline="Higher",
                url="https://example.com/b",
                source="AP",
                published_at=now,
                relevance=0.95,
                summary="DOE announced new uranium reserve program.",
            ),
        ]
    )
    await db.flush()

    lines = await get_catalyst_lines(db, ["UUUU"])

    assert lines == {"UUUU": "DOE announced new uranium reserve program."}


async def test_get_catalyst_lines_prefers_summary_falls_back_to_headline(db):
    db.add(
        NewsItem(
            symbol="CCJ",
            headline="Headline text",
            url="https://example.com/c",
            source="AP",
            published_at=datetime.now(timezone.utc),
            relevance=0.8,
            summary=None,
        )
    )
    await db.flush()

    assert await get_catalyst_lines(db, ["CCJ"]) == {"CCJ": "Headline text"}


async def test_get_catalyst_lines_only_returns_requested_symbols(db):
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            NewsItem(
                symbol="UUUU",
                headline="In scope",
                url="https://example.com/in-scope",
                source="AP",
                published_at=now,
                relevance=0.9,
            ),
            NewsItem(
                symbol="OTHER",
                headline="Not requested",
                url="https://example.com/not-requested",
                source="AP",
                published_at=now,
                relevance=0.99,
            ),
        ]
    )
    await db.flush()

    lines = await get_catalyst_lines(db, ["UUUU"])

    assert set(lines.keys()) == {"UUUU"}
