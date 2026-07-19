"""Tests for the EOD wrap's catalyst-assembly step (U11, mirroring #210's
morning-pulse catalyst injection).

Covers only the dedup + query-args + failure-degradation contract of
``_build_eod_catalysts`` - extracted from ``send_eod_wrap``'s Celery-task
closure specifically so it's directly awaitable here instead of spinning up
the rest of the task (Yahoo/Discord/watchlist calls). Mirrors
tests/test_tasks/test_agent_strategy_task.py's monkeypatch style. Formatter
rendering itself is covered by
tests/test_services/test_briefing_formatters.py::TestEODWrapCatalysts;
``get_catalyst_lines``' own selection/neutralization logic is covered by
tests/test_services/test_catalysts.py.
"""

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.db.models.news_item import NewsItem
from app.services.notifications.formatters import EODData, format_eod_wrap
from app.tasks.alerts import _build_eod_catalysts


async def test_dedups_watchlist_symbols_before_the_catalyst_query(monkeypatch):
    """EOD's watchlist_symbols is built per-watchlist-item and can repeat a
    ticker (same symbol in multiple watchlists) - the query must only ever
    see each symbol once, same as the morning task's explicit dedup."""
    mock_get_lines = AsyncMock(return_value={})
    monkeypatch.setattr("app.services.catalysts.get_catalyst_lines", mock_get_lines)

    await _build_eod_catalysts(
        MagicMock(), ["UUUU", "CCJ", "UUUU", "EQT", "CCJ", "UUUU"]
    )

    mock_get_lines.assert_awaited_once()
    _, queried_symbols = mock_get_lines.await_args.args
    assert queried_symbols == ["UUUU", "CCJ", "EQT"]


async def test_empty_watchlist_symbols_still_calls_through(monkeypatch):
    mock_get_lines = AsyncMock(return_value={})
    monkeypatch.setattr("app.services.catalysts.get_catalyst_lines", mock_get_lines)

    catalysts, unavailable = await _build_eod_catalysts(MagicMock(), [])

    assert catalysts == {}
    assert unavailable == []
    mock_get_lines.assert_awaited_once_with(mock_get_lines.await_args.args[0], [])


async def test_query_failure_is_caught_and_marks_catalysts_unavailable(monkeypatch):
    monkeypatch.setattr(
        "app.services.catalysts.get_catalyst_lines",
        AsyncMock(side_effect=RuntimeError("db unreachable")),
    )

    catalysts, unavailable = await _build_eod_catalysts(MagicMock(), ["UUUU"])

    assert catalysts == {}
    assert unavailable == ["catalysts"]


async def test_programming_defect_logs_traceback_but_wrap_still_degrades(
    monkeypatch, caplog
):
    """The broad catch is deliberate (the wrap must still send), but a code
    defect (TypeError, not an infra failure) must be LOUD: logged via
    logger.exception - full traceback at ERROR level - never a quiet
    warning that reads as ordinary catalyst unavailability. The section
    still degrades gracefully (empty catalysts + unavailable_sections)."""
    monkeypatch.setattr(
        "app.services.catalysts.get_catalyst_lines",
        AsyncMock(side_effect=TypeError("'NoneType' object is not iterable")),
    )

    with caplog.at_level(logging.ERROR, logger="app.tasks.alerts"):
        catalysts, unavailable = await _build_eod_catalysts(MagicMock(), ["UUUU"])

    assert catalysts == {}
    assert unavailable == ["catalysts"]
    own_records = [r for r in caplog.records if r.name == "app.tasks.alerts"]
    assert any(
        r.levelno == logging.ERROR
        and r.exc_info is not None
        and r.exc_info[0] is TypeError
        for r in own_records
    ), "expected an ERROR record carrying the TypeError traceback (logger.exception)"


async def test_successful_empty_result_does_not_mark_unavailable(monkeypatch):
    """A slow news day (or an agent that has never run) is a quiet, honest
    empty dict from get_catalyst_lines - not a failure. Only an actual
    exception from the query should feed unavailable_sections."""
    monkeypatch.setattr(
        "app.services.catalysts.get_catalyst_lines", AsyncMock(return_value={})
    )

    catalysts, unavailable = await _build_eod_catalysts(MagicMock(), ["UUUU"])

    assert catalysts == {}
    assert unavailable == []


async def test_successful_nonempty_result_passes_through_and_is_available(monkeypatch):
    monkeypatch.setattr(
        "app.services.catalysts.get_catalyst_lines",
        AsyncMock(return_value={"UUUU": "DOE announced new uranium reserve program."}),
    )

    catalysts, unavailable = await _build_eod_catalysts(MagicMock(), ["UUUU"])

    assert catalysts == {"UUUU": "DOE announced new uranium reserve program."}
    assert unavailable == []


async def test_mention_laden_catalyst_neutralized_through_the_eod_path(db):
    """End-to-end: a real DB row with Discord mention syntax, run through
    the real get_catalyst_lines (via _build_eod_catalysts) and then the real
    format_eod_wrap - the mention must never reach the rendered message."""
    db.add(
        NewsItem(
            symbol="UUUU",
            headline="@everyone big catalyst, buy now",
            url="https://example.com/eod-mention",
            source="AP",
            published_at=datetime.now(timezone.utc),
            relevance=0.9,
            summary=None,
        )
    )
    await db.flush()

    catalysts, unavailable = await _build_eod_catalysts(db, ["UUUU", "UUUU"])

    assert unavailable == []
    assert "@everyone" not in catalysts["UUUU"]

    data = EODData(
        big_movers=[{"symbol": "UUUU", "change_percent": 4.5}],
        catalysts=catalysts,
    )
    message = format_eod_wrap(data)

    assert "@everyone" not in message
    assert "everyone" in message
