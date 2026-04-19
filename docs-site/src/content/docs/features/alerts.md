---
title: Alerts
description: How price and ratio alerts work — condition types, Celery schedule, Discord delivery, and cooldown logic.
---

Alerts watch an equity price or ratio value and fire when a condition is met. Celery Beat runs the `alerts.check_all_alerts` task every 300 seconds (5 minutes). When a condition triggers, the result is posted to Discord as an embed and written to the `alert_history` table.

## Setting one up

From the UI, click "Create alert" on the Alerts page or the equity detail page. The `CreateAlertModal` component pre-fills the symbol if you open it from an equity or ratio page.

Via the API:

```http
POST /api/v1/alerts
Content-Type: application/json

{
  "name": "CCJ Below $40",
  "equity_symbol": "CCJ",
  "condition_type": "below",
  "threshold_value": 40.00,
  "cooldown_minutes": 60,
  "is_active": true
}
```

Use `equity_symbol` for equities or `ratio_id` (integer FK) for ratios — not both. The service calls `EquityService.get_or_create_equity` so you do not need to pre-register the symbol.

`comparison_period` is required when `condition_type` is `percent_up` or `percent_down`. Valid values are `"1d"`, `"1w"`, and `"1m"`.

## Condition types

| Value | Fires when |
| --- | --- |
| `above` | current value > threshold (also checks intraday high) |
| `below` | current value < threshold (also checks intraday low) |
| `crosses_above` | value was below threshold and is now above (or intraday high crossed above) |
| `crosses_below` | value was above threshold and is now below (or intraday low crossed below) |
| `percent_up` | value has risen >= threshold% over the comparison period |
| `percent_down` | value has fallen >= threshold% over the comparison period |

`above` and `below` use the intraday high/low from the Yahoo Finance quote so a price spike or dip that recovers before the 5-minute poll still fires. `crosses_above` and `crosses_below` store state in the `was_above_threshold` column — the first check after creation only establishes a baseline and does not trigger.

### Percent-change conditions and the price_history gap

`percent_up` and `percent_down` compute change relative to a historical close price. `AlertService._get_historical_reference_value` maps the `comparison_period` to a lookback duration (`1d` → 1 day, `1w` → 7 days, `1m` → 30 days), then calls `_get_closest_close` to find the nearest row in the `price_history` hypertable within a ±3-day window.

**There is currently no scheduled task or API endpoint that writes to `price_history`.** If the table is empty, percent-change alerts will not fire even when the price condition is met — `_evaluate_condition` returns `False` with the message "No price history for {period} lookback". This is a known gap. See the [data flow page](/architecture/data-flow/) for the full alert loop description.

## Cooldown

Each alert has a `cooldown_minutes` column (default `60`, minimum `1`, maximum `10080`). After a trigger, `AlertService._check_cooldown` compares `datetime.now(UTC)` against `last_triggered_at + timedelta(minutes=cooldown_minutes)`. If the cooldown has not elapsed, the alert is skipped — no history row is written and no notification is sent for that poll cycle.

The `last_triggered_at` column is updated on every trigger (including ones suppressed by cooldown? — no: cooldown suppression returns early before updating `last_triggered_at`). So re-triggering the cooldown clock requires an actual notification send.

## Discord delivery

The webhook URL is read from the `DISCORD_WEBHOOK_URL` environment variable. If that variable is not set, `DiscordNotificationService._get_webhook_url` falls back to the `DISCORD_WEBHOOK_URL` key in the `user_settings` table, which you can configure from the Settings page in the UI.

See [configuration](/running/configuration/) for the full environment variable reference.

When an alert fires, `discord_service.send_alert_notification` posts a Discord embed with these fields:

- title: "Alert Triggered: {alert.name}"
- description: "{target_symbol} ({target_name}) is {condition description}"
- Current Value (inline)
- Threshold (inline)
- Type — "Equity" or "Ratio" (inline)
- Notes (if set on the alert, truncated to 200 characters)

The embed color is green (`0x00FF00`) for `above`, `crosses_above`, and `percent_up`; red (`0xFF0000`) for the remaining three. Discord returns HTTP 204 on success; anything else is treated as a failure, logged, and written to `alert_history.notification_error`.

You can verify your webhook is reachable without waiting for a real trigger:

```http
POST /api/v1/alerts/notifications/test
```

## Alert history

Every trigger that passes the cooldown check creates an `AlertHistory` row before the notification is sent:

| Column | Notes |
| --- | --- |
| `triggered_at` | server timestamp (UTC) |
| `triggered_value` | the price or ratio value that fired the alert |
| `threshold_value` | snapshot of the threshold at trigger time |
| `notification_sent` | `true` if Discord returned 204 |
| `notification_channel` | `"discord"` on success, `null` otherwise |
| `notification_error` | error message if the POST failed |

Retrieve history for all alerts: `GET /api/v1/alerts/history`. Per-alert history (most recent 50 by default): `GET /api/v1/alerts/{alert_id}/history`.

## Daily digests

Beyond per-alert triggers, two scheduled tasks send broader summaries to the same Discord webhook:

- `alerts.send_morning_pulse` — futures (ES=F, NQ=F, RTY=F), VIX, 10Y yield, overnight commodity moves, today's economic calendar, pre-market movers from watchlists, and overnight alert count. Fires at a configurable time stored in user settings (default `08:00` ET, weekdays only).
- `alerts.send_eod_wrap` — market close data for SPY/QQQ/IWM/VIX/TNX/DXY, theme watchlist performance, triggered alerts summary, and tomorrow's calendar. Default `16:30` ET.

Both tasks are dispatched by `alerts.check_notification_schedule`, which runs every 60 seconds and compares the current ET time against stored settings. A "last sent date" key prevents double-sends within the same day.

## Known limitations

- Percent-change conditions (`percent_up`, `percent_down`) are non-functional until `price_history` is populated. No write path exists today.
- The 5-minute poll interval means a price can briefly cross a threshold and recover without being caught, unless the Yahoo Finance quote's intraday high/low captures the breach. For ratio alerts there is no intraday high/low, so brief crosses between polls will be missed.
- The `check_all_alerts` task processes alerts sequentially; a large number of active alerts will extend the wall-clock time of each run.
- In demo mode (`DEMO_MODE=true`), the entire beat schedule is replaced and `alerts.check_all_alerts` does not run.

---

Related: [data flow — alert loop](/architecture/data-flow/) · [domain model — Alert and AlertHistory tables](/architecture/domain-model/) · [stack decision — why Celery](/design-decisions/stack/)
