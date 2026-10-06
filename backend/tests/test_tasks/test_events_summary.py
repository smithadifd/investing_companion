"""refresh_all_watchlist_events: per-symbol failures are counted and visible."""

from unittest.mock import AsyncMock

from app.tasks.events import _refresh_symbols


async def test_summary_counts_ok_and_failed():
    async def refresh(symbol):
        if symbol == "BAD":
            raise RuntimeError("yahoo down")
        return [object(), object()]

    service = type("S", (), {"refresh_equity_events": staticmethod(refresh)})()
    session = AsyncMock()
    result = await _refresh_symbols(service, ["AAA", "BAD", "CCC"], session, delay=0)

    assert result["symbols_checked"] == 3
    assert result["ok"] == 2
    assert result["failed"] == 1
    assert result["errors"] == 1
    assert result["failed_symbols"] == ["BAD"]
    assert result["events_created"] == 4
    session.rollback.assert_awaited_once()
