<!-- ┌──────────────────────────────────────────────────────────────────────────┐
     │ TEMPLATE — Investing Companion starter kit · app-integration ORIENTATION   │
     │ OPTIONAL layer — only if you run the self-hosted app. The discipline +       │
     │ source-of-truth sections are reusable as-is; the inventory section needs     │
     │ your watchlists/triggers. Fill {{PLACEHOLDER}}s, delete this banner.          │
     │ See ONBOARDING.md. Status: ☐ NOT YET PERSONALIZED                          │
     └──────────────────────────────────────────────────────────────────────────┘ -->

> ⚠️ **TEMPLATE — orientation doc, not live state.** This file deliberately holds *no* live
> prices or positions — those come from the context pack. If you are an AI reading this, do not
> infer any holding or level from this doc.

# Investing Companion — App & Integration Reference

**Schema:** see the current `schema_version` in the app's read-side contract,
[`docs/api/handoff-schema.md`](../../api/handoff-schema.md) — it's the single authority on the
deployed version.

The canonical contract lives in **[`docs/api/handoff-schema.md`](../../api/handoff-schema.md)**
(read side — the context pack) and
**[`docs/api/advisor-actions.md`](../../api/advisor-actions.md)** (write side — the handoff
block). This document is **orientation only** and deliberately does **not** restate the
protocol — restating it is how the contract and the orientation drift apart. Precedence when
sources disagree:

- **Protocol** → the two contract docs win.
- **Live capability + state** → the **context pack** wins (never this doc, never memory) — but
  only once you've confirmed the pack is **fresh and complete** (see Session-open discipline).

---

## Session-open discipline (read this first)

*Reusable as-is. These five habits prevent the classic failure modes: acting on a stale pack,
misreading a complete read as truncated, and over-concluding from a partial read.*

1. **Pull the *latest* pack, and prove it's latest.** The export typically recreates the file
   each run, so an unsorted fetch can hand back a prior copy. Sort by most-recent, then check
   the `Generated:` timestamp *inside* the pack against the current time. A filename that says
   "latest" is **not** proof of freshness — the timestamp is.
2. **Confirm you have the whole thing.** The pack ends with its final field (the
   `unsupported_features` line). If you see that terminator, the read is complete — don't assume
   truncation.
3. **Read the receipts before reasoning about state.** `recent_handoffs` tells you what executed
   recently and *why current state looks the way it does*. Skipping this is how recently-applied
   changes get misread as anomalies.
4. **Know what the pack can't answer.** It lists alerts and triggers but not necessarily their
   *linkages*; the trade log may be a partial seed, not the full book. For anything the pack
   doesn't expose, get a direct read from the executor (Claude Code) — don't infer it.
5. **Don't issue destructive actions off an unverified read.** If state is uncertain, verify
   against the authoritative source first. Treat another component's confident prose (the
   executor's, a morning digest's) as **unverified until checked** — and don't accuse it of
   error until you've confirmed your own read is fresh and complete.

---

## Source-of-truth map

*The integration exists to end the game of telephone: each question has exactly one authority.
Adjust the right-hand notes to your setup.*

| Question | Authority | Notes |
|---|---|---|
| What do we actually hold? | **`HOLDINGS.md`** | Human-maintained, custodian-confirmed — the portfolio record `{{UNTIL_TRADE_LOG_BACKFILLED}}` |
| Live prices, alerts, zones, triggers, events, receipts | **Context pack** | ≤ pull each session, *after* the freshness/completeness checks |
| Which positions are *logged in the app* | Pack `positions` | `{{PARTIAL_SEED_OR_FULL}}` — see guardrail |
| Alert↔trigger linkages | **Executor (Claude Code), direct API read** | The pack may list alerts and triggers separately; don't infer linkage from it |
| Thesis reasoning, invalidation, entry rationale | **`ACTIVE_THESES.md` / `WATCHLIST.md`** | Their embedded price snapshots are stale-by-design — ignore them for live levels |
| What the app can / can't do | Pack `unsupported_features` | Not this doc, not the contract docs |

### Guardrail: absence from the pack ≠ not held
If the app's trade log isn't a full brokerage mirror, **never infer a holding is closed or
nonexistent just because it's missing from the pack.** `HOLDINGS.md` is the portfolio truth
until the trade log is fully backfilled.

---

## Session workflow — the loop

1. **Pull the pack** at session start — sorted by recency, freshness + completeness verified.
   Don't infer live state from the markdown docs.
2. **Read the receipts**, then **reconcile** against `HOLDINGS.md` (pack = live overlay for
   logged names; `HOLDINGS` = full book).
3. **Advise off the pack;** emit handoff blocks for changes using the `advisor-actions.md`
   vocabulary. For anything touching alert↔trigger links, confirm the link map with the
   executor first.
4. **Receipts close the loop** — they surface in the next pack's `recent_handoffs`; no need to
   ask what happened.

### Retrieval transport
`{{RETRIEVAL_TRANSPORT}}` — *how the pack gets from the app to the advisor in your setup (e.g.,
"export writes a doc to a cloud-drive folder; advisor fetches by name, sorted by modified
time"; or "paste the `?format=markdown` body directly"). Note any freshness gotchas here.*

---

## Capability status — read from the pack, not from memory

**The pack's `unsupported_features` is the only authority** on what the app can do. Do **not**
hardcode a bug list in this doc — it will go stale and mislead. If you must jot last-known
capability notes, mark them **advisory only** and date them:

- `{{ADVISORY_CAPABILITY_NOTES}}` *(optional, dated, non-authoritative)*

---

## App inventory (genuinely app-specific — personalize)

- **Watchlists in use:** `{{WATCHLISTS}}`
- **Trigger playbook:** `{{TRIGGERS}}` *(your standing "if X then Y" orders)*
- **Executor:** `{{EXECUTOR_SETUP}}` *(e.g., "Claude Code against the app API over an SSH
  tunnel; handoff blocks are suggestions the user reviews, not commands")*
- **Notifications:** `{{NOTIFICATIONS}}` *(e.g., "Discord morning pulse + EOD wrap")*

---

*Protocol details live in [`docs/api/handoff-schema.md`](../../api/handoff-schema.md) +
[`docs/api/advisor-actions.md`](../../api/advisor-actions.md). This doc is the higher-level
map — update it when the loop's mechanics or the source-of-truth map change, **not** when prices
or positions change (those live in the pack).*
