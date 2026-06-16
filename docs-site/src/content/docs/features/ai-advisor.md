---
title: AI advisor (handoff loop)
description: Connect an external Claude project to the app as a portfolio advisor, with a two-way context-pack and handoff-block loop.
---

The [AI analysis](/features/ai-analysis/) panel answers questions about one equity. The AI advisor is a different, optional capability: an external Claude project that reasons over your *whole* portfolio state — positions, alerts, watchlist targets, the trigger playbook, recent trades — and proposes changes the app can apply. It connects through a two-way "handoff loop" rather than living inside the app.

This is an advanced, opt-in integration. The app runs fine without it; nothing here is required to use any other feature.

## The loop

```
advisor --(handoff block)--> executor (Claude Code) --(API calls)--> IC
   ^                                                                  |
   |                                                                  v
   +---- context pack (incl. execution receipts) <---- GET /export/context-pack
```

Three roles:

- The **app** exports a *context pack* — a point-in-time snapshot of your portfolio state.
- The **advisor** (your Claude project) reads the pack each session and, when it wants to change something, emits a *handoff block*: a plain-language action list.
- The **executor** (Claude Code, run against the app's API) applies those actions and posts a receipt, which shows up in the next pack. The loop closes itself — the advisor learns what actually happened without being told.

The advisor never touches the API directly. It only reads the pack and emits suggestions; a human-reviewed executor does the writing.

## The context pack

`GET /api/v1/export/context-pack` (auth required) returns the pack. The default is JSON for tooling; `?format=markdown` renders it for pasting into a conversation. It is cache-first — the export makes no live market-data calls, so prices are at most one alert-check cycle old and daily closes come from the last completed sync.

The pack is assembled in `backend/app/services/context_pack.py` and typed in `backend/app/schemas/context_pack.py`. Top-level fields include `positions` (per account), `exposures` and `catalyst_exposures`, `active_alerts`, `watchlist_targets` (with per-tier entry zones), `upcoming_events`, `triggers` (the standing-order playbook), `recent_handoffs` (execution receipts), `lessons` (the learning loop), `trade_summary`, and `unsupported_features`.

That last field is load-bearing: `unsupported_features` is the **live authority** on what the app can do. The advisor must not emit any action that depends on something listed there, and the list shrinks as features ship — so capability changes propagate through the pack itself, not through a doc that can go stale.

## Handoff blocks and execution receipts

A handoff block is a markdown action list. The vocabulary covers alerts (`ADD_ALERT`, `MODIFY_ALERT`, `REMOVE_ALERT`), watchlist edits (`ADD_TO_WATCHLIST`, `UPDATE_WATCHLIST_ITEM`, `CREATE_WATCHLIST`), ratios, calendar events, trades (`LOG_TRADE`), the trigger playbook (`ADD_TRIGGER`, `UPDATE_TRIGGER`, `RETIRE_TRIGGER`), and lessons (`ADD_LESSON`). Two conventions keep it safe: targets are referenced by name or symbol, never raw IDs (the executor resolves them), and anything that spends money or changes a position is marked approval-required, which the executor skips unless the mark is present.

After running a block, the executor posts to `POST /api/v1/export/handoff-receipts` (auth; blocked in demo mode). Each action comes back `applied`, `skipped`, or `flagged`, and the receipt surfaces in the next pack's `recent_handoffs`.

## Versioning and drift detection

The pack carries two independent version stamps so an advisor can tell when its uploaded contract copy has fallen behind the deployed app:

- `schema_version` — the read-side pack shape (currently `1.6`).
- `advisor_actions_version` — the write-side action vocabulary (currently `1.1`).

They move independently: a pure write-vocabulary change (a new action that adds no pack field) bumps only `advisor_actions_version`. Both are emitted in the markdown header — `# IC Context Pack (v1.6, actions v1.1)` — and an advisor compares each against the version stamped in its uploaded copy of the matching contract doc. If a pack version is higher, that doc is behind and should be re-uploaded. For the rationale behind keeping the two halves split, see [AI integration approach](/design-decisions/ai-integration/).

## The contract

Two documents define the protocol and are uploaded to the advisor as project knowledge:

- [`docs/api/handoff-schema.md`](https://github.com/smithadifd/investing_companion/blob/main/docs/api/handoff-schema.md) — the read side: every field the context pack exposes.
- [`docs/api/advisor-actions.md`](https://github.com/smithadifd/investing_companion/blob/main/docs/api/advisor-actions.md) — the write side: the exact action vocabulary the advisor may emit.

Both hold the protocol only — no hosts, credentials, or internal IDs. The executor holds the API mapping and resolves names to IDs.

## Recreating the advisor for your own portfolio

The [advisor starter kit](https://github.com/smithadifd/investing_companion/tree/main/docs/advisor-starter-kit) is a fill-in-the-blanks scaffold for standing up your own advisor: an operating-system instructions file, blank portfolio-state templates, and the optional app-integration layer that wires in this loop. Open it in Claude Code and walk through [`ONBOARDING.md`](https://github.com/smithadifd/investing_companion/blob/main/docs/advisor-starter-kit/ONBOARDING.md) — it interviews you and fills the templates. The portfolio templates ship blank and contain no personal data.

## Delivery

How the pack reaches the advisor is up to your setup. The simplest path is pasting the `?format=markdown` body into the conversation. There is also an outbox publisher (`backend/app/services/context_pack_outbox.py`) that writes the latest pack and the two contract docs to a folder, so an advisor can fetch the most recent copy by name. Either way the discipline is the same: confirm the pack is fresh and complete before reasoning from it, and read the receipts before drawing conclusions about current state.
