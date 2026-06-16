<!-- ┌──────────────────────────────────────────────────────────────────────────┐
     │ POINTER — Investing Companion starter kit · app-integration (READ side)     │
     │ Not a copy of the contract. The live, maintained read-side contract lives    │
     │ in the app repo and is kept in sync with what the app actually exports.       │
     │ Upload THAT file to the advisor verbatim. OPTIONAL layer.                    │
     └──────────────────────────────────────────────────────────────────────────┘ -->

# Handoff Loop Schema — read side (pointer)

This is the **read-side** contract: the context pack the advisor consumes from
`GET /api/v1/export/context-pack`. It is **not** maintained here.

The canonical, version-stamped contract is part of the app and is kept in sync with what the
backend actually emits:

➡️ **[`docs/api/handoff-schema.md`](../../api/handoff-schema.md)**

Upload **that** file to your advisor verbatim — it carries the current `schema_version` and the
exact field list. This pointer exists so the starter kit names the read-side contract without
keeping a second copy that could drift out of sync.

The write side is in [`advisor-actions.md`](./advisor-actions.md) (also a pointer).
