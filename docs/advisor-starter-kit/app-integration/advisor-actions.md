<!-- ┌──────────────────────────────────────────────────────────────────────────┐
     │ POINTER — Investing Companion starter kit · app-integration (WRITE side)    │
     │ Not a copy of the contract. The live, maintained write-side vocabulary lives │
     │ in the app repo and is kept in sync with the actions the executor supports.   │
     │ Upload THAT file to the advisor verbatim. OPTIONAL layer.                    │
     └──────────────────────────────────────────────────────────────────────────┘ -->

# Advisor Action Vocabulary — write side (pointer)

This is the **write-side** contract: the action vocabulary the advisor emits in a handoff
block (`ADD_ALERT`, `ADD_TO_WATCHLIST`, `LOG_TRADE`, `ADD_TRIGGER`, …). It is **not**
maintained here.

The canonical vocabulary is part of the app and is kept in sync with the actions the executor
actually implements:

➡️ **[`docs/api/advisor-actions.md`](../../api/advisor-actions.md)**

Upload **that** file to your advisor verbatim — it carries the current action table, required
fields, and the write-vocabulary changelog. This pointer exists so the starter kit names the
write-side contract without keeping a second copy that could drift out of sync.

The read side is in [`handoff-schema.md`](./handoff-schema.md) (also a pointer).
