# Daily price-history pin compatibility — CK4

**Recommendation: KEEP the daily Yahoo pin. Confidence: high for the current code boundary; low for asserting provider-basis equivalence without upstream evidence.**

This is a bounded, offline study on draft-PR #328 head `93f7000`. It does not change a provider, schema, task schedule, or stored series. NY-102 settled quote latency only; it did not settle daily-bar adjustment compatibility.

## Decision

Keep `YahooFinanceProvider()` explicitly injected by `backend/app/tasks/price_history.py:28`. Removing it would let the Massive-primary chain overwrite a Yahoo-origin two-year series over each one-month overlap. `PriceHistoryService.sync_equity` uses `(equity_id, timestamp)` as the sole conflict key and replaces all OHLCV fields (`backend/app/services/price_history.py:96-139`); it records neither provider nor adjustment basis. A mixed basis can therefore be silently persisted and read as one series.

The checked-in adapters do not establish that Yahoo's `Ticker.history()` default output and Massive's `adjusted=true` aggregate output have equivalent split/dividend rules or matching daily-bar timestamps. The synthetic cases below faithfully exercise the transformations after those upstream values enter this code, but they cannot manufacture upstream equivalence. CK4's default for that exact unknown is KEEP.

## Traced persistence boundary and readers

| Boundary / reader | Actual behavior | Compatibility consequence |
| --- | --- | --- |
| Daily writer: `tasks/price_history.py:24-29` | Explicit Yahoo provider; Celery runs at `21:15 UTC` (`tasks/celery_app.py:91-96`). | The pin is the current daily basis choice. |
| On-demand alert backfill: `services/alert.py:1816-1834` | `AlertService` injects the same Yahoo instance into `PriceHistoryService` at `:88-99`; backfill is flushed in the alert transaction. | A removed task pin alone would still leave Yahoo writes on missing coverage; mixed series remain possible. |
| Write/upsert: `services/price_history.py:83-139` | First fetch is `2y`, later fetch is `1mo`; each nonzero-close row replaces open/high/low/close/volume on `(equity_id, timestamp)`. `adj_close` is not written. | A provider switch rewrites the trailing month only; no basis provenance or migration guard exists. |
| Percent change, including ratio components: `services/alert.py:1679-1785` | Nearest stored `close` within ±3 days of the lookback target; ratio divides two stored closes. | Dividend/basis differences change reference thresholds; timestamp differences can choose a different row. |
| Percent from high: `services/alert.py:1787-1814` | Maximum stored `high` since the lookback. | Split/basis differences change the peak and alert threshold. |
| Context-pack target status: `services/context_pack.py:319-369` | Reads latest stored `close` for watchlist target distance. | Not an alert evaluator, but it is the only other application `PriceHistory` value reader and exposes the same mixed latest close. |
| Other history APIs | `EquityService` and `RatioService` call provider history directly; they do not read `price_history` (`services/equity.py:89-115`, `services/ratio.py:226-281`). | Out of the persisted-reference boundary; not changed by this pin. |

Search of `backend/app` for `PriceHistory.(open|high|low|close|timestamp)` and `select(PriceHistory` found no other persisted-value reader. `PriceHistory` has an `adj_close` column but the writer never supplies or updates it (`db/models/price_history.py:29-38`, `services/price_history.py:106-132`).

## Adapter semantics established offline

| Case | Synthetic adapter input and observed result | Established | Not established |
| --- | --- | --- | --- |
| Split | Yahoo-frame `Close=50`; Massive aggregate `c=50`; both adapters emit `Decimal("50")`. | Both adapters preserve their supplied close; Massive sorts rows and parses epoch milliseconds. | Whether their real upstream values make the same split adjustment. |
| Dividend | Yahoo-frame `Close=99`; Massive aggregate `c=100`; outputs remain 99 and 100. | Neither adapter normalizes price basis after input. A one-unit difference reaches alert/reference storage. | Whether live Yahoo/Massive report this exact difference for any symbol/date. |
| Date boundary | Yahoo frame index `2026-11-02T00:00:00-05:00`; Massive `t=2026-11-02T00:00:00Z`. Adapter values survive; `_to_utc` yields `05:00Z` versus `00:00Z`. | The writer keys exact normalized timestamps, not a market date. A mismatch can create two rows rather than an upsert. | The real daily aggregate timestamp convention for the selected Massive entitlement and Yahoo exchange-index convention for every instrument. |
| Incomplete session | Same Massive timestamp first emits close 105 then 111. Parser accepts both; the existing service test proves same-key re-sync replaces the finalized close. | No adapter/session-completeness marker prevents a partial daily bar from persisting; same key can finalize by upsert. | Whether either upstream returns an incomplete daily bar at the `21:15 UTC` schedule, and whether their bar timestamps collide. |

Yahoo calls `ticker.history(period=period, interval=interval)` without an explicit `auto_adjust` argument (`services/data_providers/yahoo.py:383-420`). Massive calls aggregates with `adjusted=true` (`services/data_providers/massive.py:792-811`). These are upstream request/default semantics, not transformations implemented in this repository. `yfinance` is pinned to `1.1.0` (`backend/requirements.txt:40-46`), but this study intentionally made no network call or copied paid response; it therefore does not convert either provider's external documentation into observed production behavior.

## Reproducible offline comparison

The following was run with no network transport, a fake `yf.Ticker.history` DataFrame, `Massive.parse_aggregates`, and the real `_to_utc` seam:

```bash
PYTHONPATH=backend backend/.venv/bin/python /tmp/ck4_history_pin_compat.py
```

Expected output:

```text
split 50 50
dividend 99 100
boundary 2026-11-02T00:00:00-05:00 2026-11-02T00:00:00 2026-11-02T05:00:00+00:00 2026-11-02T00:00:00+00:00
incomplete 105 111 2026-06-03T00:00:00
```

To reproduce without retaining that temporary runner, use this self-contained script as `/tmp/ck4_history_pin_compat.py`; it deliberately replaces no repository code and makes no provider call:

```python
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
import pandas as pd
from app.services.data_providers import yahoo as y
from app.services.data_providers.massive import parse_aggregates
from app.services.data_providers.yahoo import YahooFinanceProvider
from app.services.price_history import _to_utc

async def direct(fn, *args): return fn(*args)
class Ticker:
    def __init__(self, frame): self.frame = frame
    def history(self, **_): return self.frame
async def yahoo(frame):
    ticker, executor = y.yf.Ticker, y.run_in_executor
    try:
        y.yf.Ticker, y.run_in_executor = lambda _: Ticker(frame), direct
        return (await YahooFinanceProvider().get_history("CASE"))[0]
    finally:
        y.yf.Ticker, y.run_in_executor = ticker, executor
def massive(ts, close):
    return parse_aggregates({"results": [{"t": int(ts.timestamp()*1000), "o": close, "h": close + 1, "l": close - 1, "c": close, "v": 100}]})[0]
async def main():
    frame = lambda day, close: pd.DataFrame({"Open":[close], "High":[close+1], "Low":[close-1], "Close":[close], "Volume":[100]}, index=pd.DatetimeIndex([day]))
    split_y, split_m = await yahoo(frame(datetime(2026, 6, 1, tzinfo=ZoneInfo("America/New_York")), 50)), massive(datetime(2026, 6, 1, 4, tzinfo=timezone.utc), 50)
    div_y, div_m = await yahoo(frame(datetime(2026, 6, 2, tzinfo=ZoneInfo("America/New_York")), 99)), massive(datetime(2026, 6, 2, 4, tzinfo=timezone.utc), 100)
    edge_y, edge_m = await yahoo(frame(datetime(2026, 11, 2, tzinfo=ZoneInfo("America/New_York")), 100)), massive(datetime(2026, 11, 2, tzinfo=timezone.utc), 100)
    partial, final = massive(datetime(2026, 6, 3, tzinfo=timezone.utc), 105), massive(datetime(2026, 6, 3, tzinfo=timezone.utc), 111)
    assert split_y.close == split_m.close == Decimal("50")
    assert (div_y.close, div_m.close) == (Decimal("99"), Decimal("100"))
    assert (_to_utc(edge_y.timestamp), _to_utc(edge_m.timestamp)) == (datetime(2026, 11, 2, 5, tzinfo=timezone.utc), datetime(2026, 11, 2, tzinfo=timezone.utc))
    assert partial.timestamp == final.timestamp and partial.close != final.close
asyncio.run(main())
```

Relevant non-network checks:

```bash
cd backend && .venv/bin/pytest tests/test_services/test_massive_provider.py::TestHistory tests/test_services/test_price_history_service.py tests/test_services/test_primary_consumers.py
```

## Exact unknowns and removal boundary

Unknowns that block removal: (1) actual Yahoo `Ticker.history()` adjustment/default behavior under the pinned dependency for split and cash-dividend events; (2) actual Massive `adjusted=true` adjustment behavior for those same events and entitlement; (3) real timestamp/date identity of both daily feeds; and (4) incomplete-session availability/finalization at the fixed task time. The checked-in transformation seams cannot faithfully represent those upstream facts.

If a future, authorized evidence collection establishes equivalence, the unapplied removal boundary is deliberately narrow: change only `backend/app/tasks/price_history.py` to stop injecting `YahooFinanceProvider`, allowing `PriceHistoryService` to resolve the elected chain; update `backend/tests/test_services/test_primary_consumers.py::test_daily_history_task_pins_yahoo` to assert that selection instead; add provider-basis/timestamp fixtures at the existing adapter and persistence boundaries. Do **not** rewrite existing rows, alter `AlertService`'s explicit Yahoo injection, change the schema, or migrate stored series in that follow-on without a separate decision.

## D-records and scheduled REGROUP

- **D1 — KEEP:** Daily history remains pinned to Yahoo because persisted alert/reference readers have no basis provenance and adapter-only evidence cannot establish upstream equivalence.
- **D2 — separation preserved:** NY-102's accepted 15-minute quote delay authorizes no daily-history basis change.
- **D3 — no implied implementation:** This report schedules a Claude/Andrew **REGROUP** to decide whether authorized upstream evidence is worth collecting and, only after it exists, whether to build the narrow removal boundary above. No removal build follows from this artifact.
