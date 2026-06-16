# App-Integration Layer (OPTIONAL)

**Skip this whole folder unless you run the self-hosted Investing Companion app.** The advisor
operating-system (`PROJECT_INSTRUCTIONS.md`) and the portfolio docs (`docs/`) work perfectly
well on their own. This layer is the advanced add-on that connects a *live* data loop to the
advisor.

## What it does

It closes the loop between three roles:

```
advisor ──(handoff block)──▶ executor (Claude Code) ──(API calls)──▶ Investing Companion app
   ▲                                                                          │
   │                                                                          ▼
   └──────── context pack (prices, alerts, triggers, receipts) ◀──── GET /export/context-pack
```

- The **app** exports a *context pack*: live prices, alerts, entry zones, triggers, upcoming
  events, and execution receipts.
- The **advisor** (your Claude project) reads the pack each session and, when it wants to
  change something, emits a *handoff block* — a plain-language action list.
- The **executor** (Claude Code, in your app repo) runs those actions against the app's API and
  posts a receipt, which shows up in the next pack. The loop closes itself.

## The three docs here

- **`INVESTING_COMPANION.md`** — orientation: session-open discipline and the source-of-truth
  map. *Read-side behavior.* This is the one you most need to personalize to your app's
  watchlists and triggers.
- **`handoff-schema.md`** — a **pointer** to the **read** contract (every field the context
  pack exposes).
- **`advisor-actions.md`** — a **pointer** to the **write** contract (the exact action
  vocabulary the advisor is allowed to emit).

## The contract docs are maintained in the app, not here

The read/write contract is part of the Investing Companion app itself, kept in sync with what
the backend actually exports and accepts. It lives at:

- **[`docs/api/handoff-schema.md`](../../api/handoff-schema.md)** — read side (context pack +
  current `schema_version`).
- **[`docs/api/advisor-actions.md`](../../api/advisor-actions.md)** — write side (action
  vocabulary + changelog).

The two files in *this* folder are thin pointers to those, so the kit never ships a second copy
that could drift out of date.

## Important

These docs describe a **protocol**, not your portfolio — they hold no personal data. The live
authority on what's supported is always the context pack's `unsupported_features` field, never a
hardcoded list in any doc.

Upload **`docs/api/handoff-schema.md`** and **`docs/api/advisor-actions.md`** to the advisor
verbatim. Personalize `INVESTING_COMPANION.md` with your own watchlists/triggers inventory.
