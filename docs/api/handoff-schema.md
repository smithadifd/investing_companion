# Handoff Loop Schema (v1.4)

The handoff loop connects an external AI advisor (e.g. a Claude project) to the app in both
directions. This document is the contract; give it to the advisor verbatim.

```
advisor --(handoff block)--> executor (Claude Code) --(API calls)--> IC
   ^                                                                  |
   |                                                                  v
   +---- context pack (incl. execution receipts) <---- GET /export/context-pack
```

## App -> conversation: the context pack

`GET /api/v1/export/context-pack` (auth required). `?format=markdown` renders for pasting
into a conversation; the default JSON is for tooling.

Top-level fields (`schema_version: "1.4"`):

| Field | Contents |
|-------|----------|
| `positions` | Open positions from the trade log: symbol, quantity, avg cost, current price/value, unrealized/realized P&L |
| `portfolio_value`, `total_invested` | Portfolio rollups |
| `exposures` | Position value per theme watchlist. **Overlapping by design** — one position can count toward several themes; do not sum |
| `active_alerts` | Every active alert with `last_checked_value` (≤5 min stale), `distance_percent` to threshold (null for percent conditions), and `status`: `armed` / `approaching` (within 3%) / `triggered_recently` (last 48h) |
| `recent_triggers` | Alert fires from the last 7 days |
| `watchlist_targets` | Items with a `target_price` and/or `entry_zones`: latest stored daily close, percent to target, thesis, and per-tier zone status. Each zone is `{tier, low, high, status, distance_percent}` with `status`: `in_zone` / `approaching` (within 3% of the entry edge) / `above` / `below` / `unknown` (no stored close). Zones are set via the watchlist item PUT (`entry_zones: [{tier, low, high}]`, ≥1 bound per zone; explicit `null` clears). A per-tier zone-hit alert exists: `ADD_ALERT` with `condition_type: entry_zone` + the watchlist item (no threshold) — it fires once per tier on entry and re-arms only when price exits out the entry side |
| `upcoming_events` | Next 14 days of earnings/macro/custom events with `days_away` |
| `triggers` | The trigger playbook: pre-committed "if X then I do Y" standing orders with `tier`, lifecycle `status` (active/executed/retired), and live `signal` (armed/approaching/hit/unwatched, derived from linked alerts). Advisors can propose new triggers via handoff (`ADD_TRIGGER` with name, rule, action, tier, linked alert names) |
| `recent_handoffs` | Execution receipts for the last 5 handoff blocks (see below) |
| `lessons` | The learning loop's journal: the 20 most recent lessons captured at trade close, each `{symbol, thesis_outcome, lesson, tags, recorded_at}` with `thesis_outcome`: `played_out` / `partial` / `wrong` / `unclear`. Weigh these when advising on similar setups (same symbol, same theme, or shared tags). Lessons are written via `POST /api/v1/lessons` (`ADD_LESSON` handoff actions are allowed: trade_id or symbol + thesis_outcome + lesson + tags) |
| `trade_summary` | Trade count, win rate, profit factor, realized/unrealized P&L |
| `unsupported_features` | **Never emit handoff actions requiring anything listed here.** Shrinks as features ship |

Staleness: the pack makes no live market-data calls. Prices are at most one alert-check
cycle (5 min) old; daily closes are from the last completed sync.

## Conversation -> app: handoff blocks

Handoff blocks are markdown action lists executed by Claude Code against the API
(see the action table in the executor's local config). Conventions:

- Reference targets by **name/symbol, never raw IDs** — the executor resolves IDs.
- Mark actions needing explicit sign-off; the executor skips them absent approval.
- Check `unsupported_features` in the latest pack before emitting an action type.

## Execution receipts

After executing a block, the executor posts:

`POST /api/v1/export/handoff-receipts` (auth; blocked in demo mode)

```json
{
  "summary": "Q4 deferred items: defense watchlist + carry tiers",
  "source": "investing_hub",
  "actions": [
    {"action": "ADD_ALERT", "target": "KTOS", "result": "applied", "detail": "alert id 32"},
    {"action": "ADD_TO_WATCHLIST", "target": "RCAT", "result": "skipped", "detail": "dropped per user amendment"},
    {"action": "ADD_RATIO", "target": "USD/JPY", "result": "flagged", "detail": "needs forex fix"}
  ]
}
```

`result` is one of `applied` | `skipped` | `flagged`. Receipts appear in the next context
pack's `recent_handoffs`, closing the loop: the advisor learns what actually happened
without being told.

## Versioning

`schema_version` is MAJOR.MINOR. Minor bumps add fields (advisors must tolerate unknown
fields); a major bump may rename or remove. Changes are recorded here.

| Version | Change |
|---------|--------|
| 1.0 | Initial pack: positions, exposures, alerts, triggers, targets, events, trade summary, unsupported_features |
| 1.1 | Added `recent_handoffs` + the receipts endpoint |
| 1.2 | Added `triggers` (the trigger playbook) + `/api/v1/triggers` CRUD |
| 1.3 | `watchlist_targets` includes items with `entry_zones` + per-tier zone status; `entry_zone` alert condition; `tiered_entry_zones` removed from `unsupported_features` |
| 1.4 | Added `lessons` (learning-loop journal) + `/api/v1/lessons` CRUD; trade create responses gain `position_closed` |
