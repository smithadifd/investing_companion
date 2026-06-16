# Advisor Action Vocabulary

**`advisor_actions_version`: 1.1** — MAJOR.MINOR (MINOR = additive action/field/enum; MAJOR =
rename/removal). The context pack emits this same value as `advisor_actions_version`, so an
advisor can detect when *this* uploaded copy is behind: if the pack's version is higher than the
one stamped here, ask for a re-upload before relying on the vocabulary (tolerate minor gaps).
Changelog at the bottom of this file.

Companion to [`handoff-schema.md`](./handoff-schema.md). That document describes the **context
pack** the advisor *reads*; this one describes the **handoff block** the advisor *writes back*.
Upload both to the advisor (the Claude.ai investing project) as project knowledge.

This file is safe to share with the advisor: it contains the action vocabulary and constraints
only — no hosts, credentials, or internal IDs. The executor (Claude Code, in the IC repo) holds
the API mapping and resolves names to IDs.

## The loop, in one line

```text
context pack ──▶ advisor triages ──▶ HANDOFF BLOCK ──▶ executor runs API ──▶ receipt ──▶ next pack
```

The advisor's only job on the write side is to emit a **handoff block**: a markdown action list
the executor can run unambiguously.

## Handoff block format

Emit one fenced block. Start with a one-line `Summary:`, then a numbered list. Each item is an
**ACTION_TYPE — target**, followed by indented `field: value` lines. Mark anything that should not
run without explicit sign-off with `⚠️ approval required`.

```text
## Handoff block

Summary: Carry-trade tier adjustments + new defense watchlist entries

1. ADD_TO_WATCHLIST — KTOS (Crisis Playbook - Hormuz/Carry Trade)
   thesis: Defense primary on Hormuz escalation; tier-1 entry on pullback
   target_price: 18.50
   catalyst_tags: ["hormuz escalation", "defense"]

2. UPDATE_WATCHLIST_ITEM — CCJ (Uranium & Nuclear)
   entry_zones: [{tier: "starter", low: 48, high: 50}, {tier: "core", low: 44, high: 46}]

3. ADD_ALERT — KTOS
   condition_type: below
   threshold_value: 18.50
   notes: Tier-1 entry trigger

4. LOG_TRADE — CCJ
   trade_type: buy
   quantity: 100
   price: 49.20
   ⚠️ approval required
```

Conventions:

- **Refer to targets by name/symbol, never by raw ID.** The executor resolves IDs.
- **One action per list item.** Don't bundle an alert and a watchlist edit into one entry.
- **Mark approvals.** Anything that spends money or changes a position (`LOG_TRADE`,
  `REMOVE_ALERT` on a live trigger) gets `⚠️ approval required`. The executor skips unmarked-but-
  risky actions rather than guess.
- **Check `unsupported_features` in the latest pack first.** Never emit an action that depends on
  anything listed there — it will come back `flagged`.

## Action types

Fields in **bold** are required.

### Alerts

| Action | Fields |
|--------|--------|
| `ADD_ALERT` | **`equity_symbol`** *(or a ratio name)*, **`condition_type`**, **`threshold_value`**, `name`, `cooldown_minutes`, `notes`, `is_active` |
| `MODIFY_ALERT` | target = alert **name**; any of the above fields to change |
| `REMOVE_ALERT` | target = alert **name** |

`condition_type` is one of:

| Value | Meaning |
|-------|---------|
| `above` / `below` | price (or a **ratio**, by passing the ratio as the target) vs `threshold_value` |
| `crosses_above` / `crosses_below` | fires on the crossing, not while past it |
| `percent_from_high` | drawdown from the period high (`comparison_period`, e.g. `52w`) |
| `entry_zone` | fires per tier when price enters a watchlist item's entry zone — **no `threshold_value`**; target is the watchlist item. Re-arms only when price exits the entry side |

> **Do not use `percent_up` / `percent_down`** until bug #48 is fixed — `comparison_period` is
> ignored, so the alert is wrong. For "down X% today" intent, prefer `percent_from_high` or a
> `below` level.

### Watchlist

| Action | Fields |
|--------|--------|
| `ADD_TO_WATCHLIST` | **`symbol`**, target = watchlist **name**; `thesis`, `notes`, `target_price`, `track_calendar`, `entry_zones`, `catalyst_tags` |
| `UPDATE_WATCHLIST_ITEM` | target = **symbol (watchlist name)**; any of `thesis`, `notes`, `target_price`, `entry_zones`, `catalyst_tags`. Explicit `null` clears a field |
| `CREATE_WATCHLIST` | **`name`**, `description` |

- `entry_zones`: a list of `{tier, low, high}` — at least one of `low`/`high` per zone. These power
  the per-tier `entry_zone` alert and the pack's zone-status readout.
- `catalyst_tags`: lowercased single-catalyst labels (e.g. `"uranium restart"`). They drive the
  pack's `catalyst_exposures` concentration rollups — keep them consistent across items so a
  cluster aggregates correctly.

### Ratios

| Action | Fields |
|--------|--------|
| `ADD_RATIO` | **`name`**, **`numerator_symbol`**, **`denominator_symbol`**, `description`, `category` (`commodity` / `equity` / `macro` / `crypto`) |

> Forex symbols (`USD`, `JPY`, …) don't resolve yet (bug #49). Use ETF proxies — `FXY` for yen,
> `UUP` for the dollar — instead of raw currency pairs.

### Calendar

| Action | Fields |
|--------|--------|
| `ADD_CALENDAR_EVENT` | **`event_type`** (`earnings` / `fomc` / `cpi` / `ppi` / `nfp` / `gdp` / `pce` / `custom`, among others), **`title`**, **`event_date`** (`YYYY-MM-DD`), `description`, `importance` (`low` / `medium` / `high`) |

### Trades

| Action | Fields |
|--------|--------|
| `LOG_TRADE` | **`equity_symbol`**, **`trade_type`** (`buy` / `sell` / `short` / `cover`), **`quantity`**, **`price`**, `fees`, `notes` — **always `⚠️ approval required`** |

### Trigger playbook (standing orders)

| Action | Fields |
|--------|--------|
| `ADD_TRIGGER` | **`name`**, **`rule`** ("if X"), **`action`** ("then I do Y"), `tier`, linked alert **names** |
| `UPDATE_TRIGGER` | target = trigger **name**; any of `rule`, `action`, `tier`, a new `name`, linked alert **names**. Editing `rule` or `action` — the decision itself — is **⚠️ approval required**; a cosmetic `name`/`tier` change is not |
| `RETIRE_TRIGGER` | target = trigger **name**. **⚠️ approval required** (a standing order is playbook-linked, same as `REMOVE_ALERT` on a live trigger). Trigger-only — never cascades to alerts |

Triggers are pre-committed decisions, not automation — they record *what you'll do* when a level
hits, and the pack reports each one's live `signal` (armed/approaching/hit) from its linked alerts.

`UPDATE_TRIGGER` edits a standing order in place — use it when a trigger's prose goes stale (e.g. an
add ladder gets re-leveled) rather than retiring and re-adding. Notes:

- Target by trigger **name**; the executor owns name→ID. Trigger names aren't unique, so an
  ambiguous or missing name comes back `flagged`, not guessed.
- Editing `rule`/`action` is gated. The executor reads the current trigger and **only treats it as
  approved when the `⚠️` mark is present and the change actually touches `rule`/`action`** — an
  unmarked prose edit is `skipped`, same as any unmarked-but-risky action.
- Renaming or rewriting prose leaves the trigger's linked alerts untouched. Re-point links only by
  passing new linked alert **names** — and do so when a linked alert is being *removed* this session
  (the join cascades on alert delete, silently dropping the link).

`RETIRE_TRIGGER` closes a standing order that no longer applies (a thesis broke, a swing closed). It
is **terminal** — a retired trigger is history, not paused; to bring an order back, `ADD_TRIGGER` a
fresh one. Notes:

- **The trigger↔alert relationship is not symmetric, in either direction.** `REMOVE_ALERT` does *not*
  retire a linked trigger — the join cascades, the alert vanishes, but the trigger survives watching
  nothing (`signal: unwatched`). So when you remove the last alert behind a standing order, **pair it
  with a separate `RETIRE_TRIGGER`** in the same block. Conversely, `RETIRE_TRIGGER` does *not* silence
  the trigger's linked alerts — they keep firing on their own; remove or deactivate them with their own
  `REMOVE_ALERT`/`MODIFY_ALERT` if that's the intent.
- Retire when the order is dead; `UPDATE_TRIGGER` when it's only stale (re-leveled, renamed). Don't
  retire-and-re-add to make an edit.

### Lessons (learning loop)

| Action | Fields |
|--------|--------|
| `ADD_LESSON` | **`symbol`** *(or `trade_id`)*, **`thesis_outcome`** (`played_out` / `partial` / `wrong` / `unclear`), **`lesson`**, `tags` |

Lessons are captured at trade close and resurface on the trade-readiness card and in future packs.
Emit one when a closed position taught something worth weighing on the next similar setup.

## What the advisor should *not* do

- Don't emit actions for anything in the pack's `unsupported_features`.
- Don't invent action types or fields outside this table — unrecognized actions are `flagged`, not
  guessed at.
- Don't reference internal IDs; the executor owns the name→ID resolution.
- Don't bundle multiple resources into one action item.

## After execution

The executor posts a receipt (`applied` / `skipped` / `flagged` per action) that folds into the
next context pack's `recent_handoffs`. The advisor reads that to learn what actually happened —
no need to ask. If actions come back `skipped`/`flagged` repeatedly, the cause is usually a missed
approval mark, an `unsupported_features` collision, or a known bug (#48 / #49) above.

## Write-vocabulary changelog

Write-side action additions are tracked here under `advisor_actions_version` (MAJOR.MINOR),
**separate** from the context pack's `schema_version` in
[`handoff-schema.md`](./handoff-schema.md) — that version covers only the read-side pack. A pure
write-vocabulary change (a new action that adds no pack field) bumps **this** version and does
**not** move the pack `schema_version`. The pack emits the current value as
`advisor_actions_version` so the advisor can spot a stale uploaded copy.

| Version | Date | Change |
|---------|------|--------|
| 1.0 | (baseline) | Initial write vocabulary: alerts (`ADD_ALERT` / `MODIFY_ALERT` / `REMOVE_ALERT`), watchlist (`ADD_TO_WATCHLIST` / `UPDATE_WATCHLIST_ITEM` / `CREATE_WATCHLIST`), `ADD_RATIO`, `ADD_CALENDAR_EVENT`, `LOG_TRADE`, `ADD_TRIGGER`, `ADD_LESSON` |
| 1.1 | 2026-06-15 | Added `UPDATE_TRIGGER` — edit a standing order in place (`rule` / `action` / `tier` / `name` / linked alerts); `rule`/`action` edits are approval-gated. And `RETIRE_TRIGGER` — terminal close of a standing order (approval-gated, trigger-only; `POST /triggers/{id}/retire`). Both are pure write-vocab (no read-side pack field added), so pack `schema_version` stayed 1.5 |
