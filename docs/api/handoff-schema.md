# Handoff Loop Schema (v1.6)

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

Top-level fields. The pack's two version stamps are documented as rows in the table below and
deliberately **not** restated as literals here — a copy of a version number is a cache, and it goes
stale the moment either version moves. Read the stamp, never a note about the stamp:

| Field | Contents |
|-------|----------|
| `positions` | Open positions from the trade log, **one row per (account, symbol)**: symbol, `account` (account name, or null = unassigned), quantity, avg cost, current price/value, unrealized/realized P&L. The same ticker held in two accounts appears twice |
| `portfolio_value`, `total_invested` | Portfolio rollups (summed across accounts) |
| `exposures` | Position value per theme watchlist. **Overlapping by design** — one position can count toward several themes; do not sum |
| `catalyst_exposures` | Held value grouped by single-catalyst cluster (a `catalyst_tags` tag on a watchlist item, e.g. "uranium restart"): `{catalyst, symbols, value, percent_of_portfolio, position_count}`. **Overlapping** — a symbol can carry several catalysts; do not sum. Catalyst tags are set on watchlist items (`catalyst_tags: [...]`, lowercased) |
| `active_alerts` | Every active alert with `last_checked_value`, its `last_checked_at` timestamp, `distance_percent` to threshold (null for percent conditions), and `status`: `armed` / `approaching` (within 3%) / `triggered_recently` (last 48h). **`distance_percent` is `(threshold_value − last_checked_value) / last_checked_value × 100`** — it measures where the *threshold* sits relative to price, not where price sits relative to the threshold. A `crosses_above` alert reading `−7.6%` is therefore 7.6% **above** its trigger level (already through it, re-arming on a retest), not below it. Never back out a threshold from the percentage; `threshold_value` is in the same row |
| `recent_triggers` | Alert fires from the last 7 days |
| `watchlist_targets` | Items with a `target_price` and/or `entry_zones`: latest stored daily close, percent to target, thesis, and per-tier zone status. Each zone is `{tier, low, high, status, distance_percent}` with `status`: `in_zone` / `approaching` (within 3% of the entry edge) / `above` / `below` / `unknown` (no stored close). Zones are set via the watchlist item PUT (`entry_zones: [{tier, low, high}]`, ≥1 bound per zone; explicit `null` clears). A per-tier zone-hit alert exists: `ADD_ALERT` with `condition_type: entry_zone` + the watchlist item (no threshold) — it fires once per tier on entry and re-arms only when price exits out the entry side |
| `upcoming_events` | Next 14 days of earnings/macro/custom events with `days_away` |
| `triggers` | The trigger playbook: pre-committed "if X then I do Y" standing orders with `tier`, lifecycle `status` (active/executed/retired), and live `signal` (`armed`/`approaching`/`hit`/`unwatched`/`disarmed`, derived from **active** linked alerts only). `signal` is **null** on executed/retired triggers — closed history has no live signal. `disarmed` means rungs are linked but every one is deactivated: the ladder exists and nothing is watching it. Advisors can propose new triggers via handoff (`ADD_TRIGGER` with name, rule, action, tier, linked alert names) |
| `recent_handoffs` | Execution receipts for the last 5 handoff blocks (see below) |
| `lessons` | The learning loop's journal: the 20 most recent lessons captured at trade close, each `{symbol, thesis_outcome, lesson, tags, recorded_at}` with `thesis_outcome`: `played_out` / `partial` / `wrong` / `unclear`. Weigh these when advising on similar setups (same symbol, same theme, or shared tags). Lessons are written via `POST /api/v1/lessons` (`ADD_LESSON` handoff actions are allowed: trade_id or symbol + thesis_outcome + lesson + tags) |
| `trade_summary` | Trade count, win rate, profit factor, realized/unrealized P&L |
| `unsupported_features` | **Never emit handoff actions requiring anything listed here.** Shrinks as features ship |
| `advisor_actions_version` | The deployed **write-vocabulary** version (MAJOR.MINOR), stamped separately from `schema_version`. Compare it against the version in your uploaded `advisor-actions.md`; if the pack's is higher, your action vocabulary is behind — ask for a re-upload. Tolerate minor (additive) gaps. See `advisor-actions.md` for its changelog |

Staleness: the pack makes no live market-data calls. Prices are at most one alert-check
cycle (5 min) old; daily closes are from the last completed sync.

### Reading a stale distance

Only the scheduled check loop writes `last_checked_value`, and only for alerts that are
active. The moment an alert is deactivated, its stored value freezes at whatever price was
current then — and nothing about that number announces its age.

The pack no longer presents such a value as a distance. When `last_checked_at` is missing or
older than 24 hours, `distance_percent` is `null`, and a trigger whose linked alerts are all
deactivated reads `signal: disarmed` instead of `armed`.

So, when reading the pack:

- **A null `distance_percent` means "unknown", never "far away."** Do not treat the absence
  of a distance as evidence that a level is not close.
- **`disarmed` is a finding, not a status.** It says a deliberately-built price ladder has
  gone dark. Surface it; a rung nobody is watching cannot fire.
- **A null `signal` on an executed or retired trigger is expected** — that trigger is closed
  history, and deriving a live signal for it would invite acting on a decision already made.

This exists because a deactivated CCJ ladder reported `armed` at `2.78%` away while the stock
traded ~11% past the rung in the opposite direction, unwatched for three weeks (#259). A
confident wrong number is worse than no number.

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

The pack carries **two** independent version stamps: `schema_version` (this table — the read-side
pack shape) and `advisor_actions_version` (the write-side action vocabulary, changelog in
`advisor-actions.md`). They move independently — a pure write-vocab change bumps only the latter
and leaves `schema_version` untouched (e.g. the trigger-edit actions added under 1.5).

| Version | Change |
|---------|--------|
| 1.0 | Initial pack: positions, exposures, alerts, triggers, targets, events, trade summary, unsupported_features |
| 1.1 | Added `recent_handoffs` + the receipts endpoint |
| 1.2 | Added `triggers` (the trigger playbook) + `/api/v1/triggers` CRUD |
| 1.3 | `watchlist_targets` includes items with `entry_zones` + per-tier zone status; `entry_zone` alert condition; `tiered_entry_zones` removed from `unsupported_features` |
| 1.4 | Added `lessons` (learning-loop journal) + `/api/v1/lessons` CRUD; trade create responses gain `position_closed` |
| 1.5 | Multi-account: `positions` are per-account (each gains `account`); added `catalyst_exposures` (single-catalyst cluster rollups) + `catalyst_tags` on watchlist items + `/api/v1/accounts` CRUD + `trades.account_id`; removed `per_account_positions` from `unsupported_features` |
| 1.6 | Added `advisor_actions_version` top-level field — the write-vocabulary version stamp, so an advisor can detect when its uploaded `advisor-actions.md` is behind the deployed action vocabulary |
| 1.7 | Staleness is now explicit (#259). `alerts[].last_checked_at` added; `alerts[].distance_percent` and a trigger's `signal` are **null** rather than confidently wrong when the underlying value is unattended. New trigger signal `disarmed` (linked alerts exist but all are deactivated); `triggers[].signal` is null on non-active triggers. See "Reading a stale distance" below |
