---
title: Schwab adopt semantics
description: How a Schwab-reported position becomes an IC-managed position — account mapping, the synthetic trade, basis math, and the reconciliation view this unblocks.
---

This page pins the semantics for "adopting" a Schwab-reported position into Investing Companion, before any of it gets built. It is a decision record, not a build: every recommendation below is a proposal that needs to be ratified (or amended) before the next wave can implement the read-only reconciliation view it ends on.

The problem: `schwab_ingestion.pull_positions` (`backend/app/services/schwab_ingestion.py`) already lands read-only snapshots of what Schwab reports per account — see PR #216 (`981f370`), sub-PR 1 of the T2 chain, schema + client only, "no reconciliation logic, no CSV import, no UI." Investing Companion's own positions are not stored rows at all; `TradeService._calculate_positions` (`backend/app/services/trade.py:551-669`) recomputes them on every read by walking the append-and-mutate `trades` table. There is no `position` row to "adopt into" — the only way to make IC agree with Schwab is to change what the trade ledger contains. This page defines how.

For the trade ledger's actual mutation model (not the append-only model this page's predecessor assumed — see the note at the end of [Basis math](#3-basis-math-fifo-remaining-lots-not-net-cash)), see [FIFO trade matching](/design-decisions/fifo-matching/). For the Schwab OAuth/client layer, see `backend/app/services/data_providers/schwab.py` and `backend/app/api/v1/endpoints/schwab.py`.

## 1. What model is adopted into

**Recommendation: a new `AccountLink` entity, user-scoped, mapping one Schwab `account_hash` to one IC `Account` — created by explicit user action, never automatically.**

`Account` (`backend/app/db/models/account.py:24-59`) has no Schwab-hash or external-link column at all. On the ingestion side, `ImportedPosition`, `ImportedTransaction`, and `BrokerImportRun` (`backend/app/db/models/broker_import.py:61-286`) carry only Schwab's opaque `account_hash` (e.g. `broker_import.py:166`, `:235`) — never a foreign key to `accounts.id`. Today there is no code path that can say "this Schwab account_hash is my Roth." That mapping has to be built, and it has to be built before anything else in this document, because every later question (basis, staleness, the view) is keyed on "which IC account does this hash mean."

The mapping cannot be inferred automatically. `SchwabProvider.get_account_hashes()` (`backend/app/services/data_providers/schwab.py:401-444`) wraps `client.get_account_numbers()`, whose only two response fields are `accountNumber` and `hashValue` (documented in the PR #216 method table) — and `redact_account_fields` (`schwab.py:69-93`) strips `accountNumber` before anything downstream ever sees it. So the adoption flow never has a broker-supplied nickname, mask, or type to auto-match against an existing `Account` row; a hash is just an opaque, stable-but-meaningless string.

`AccountLink` fields: `id`, `user_id` (FK `users.id`, CASCADE — the existing convention on every user-scoped table here), `account_hash` (String(128), matching `broker_import.py`'s column width), `source` (String(50), default `"schwab_api"`, broker-agnostic like `broker_import`'s `source` column so a future CSV-imported account can reuse the shape), `account_id` (nullable FK `accounts.id`, `ON DELETE SET NULL` — mirrors `Trade.account_id`'s exact convention at `trade.py:85-89`), `status` (`active` / `orphaned`, see [§4](#4-account-hash-account-mapping-lifecycle)), plus the standard `TimestampMixin`. Unique on `(user_id, account_hash)`.

**Alternatives considered:**
- *Auto-create a new `Account` per discovered hash.* Rejected: without a broker-supplied label, the created account would be named something meaningless like "Schwab Account 3d9f," and a user who already has a hand-named "Roth" `Account` they've been logging trades into would end up with two rows for the same real-world account. Silent duplication is worse than a one-time linking prompt.
- *Skip `Account` entirely; key everything off `account_hash` directly.* Rejected: it would bypass the existing multi-account model (`account.py`'s docstring: "the same ticker held in two accounts... is two distinct positions") and every downstream position/P&L call (`_calculate_positions(by_account=True)`, `trade.py:574-576`) that already partitions by `account_id`.

**Consequences:** adoption cannot happen for a hash with no `AccountLink` row, or one whose `account_id` is still null. The UI must surface unlinked hashes ("Unlinked Schwab account, hash ending `…XXXX`") and force a link-or-create-account step first — this is a hard gate, not a nice-to-have, because every later semantic in this doc assumes the mapping exists.

- [ ] RATIFIED / - [ ] AMENDED: ___

## 2. Synthetic-opening vs. delta-adjustment trades

**Recommendation: delta-adjustment trades, with synthetic-opening as the degenerate case (zero prior IC trades ⇒ delta equals the full Schwab quantity) — one mechanism, not two.**

Compute `ic_qty` for `(account_id, equity)` via the existing `_calculate_positions(by_account=True)` and `schwab_qty` from the linked hash's latest complete `ImportedPosition.quantity` (`get_latest_complete_run` + a symbol lookup, `schwab_ingestion.py:392-426`). `delta = schwab_qty - ic_qty`. If `delta == 0`, there is nothing to adopt (the UI shows "matched," no trade is written). If `delta != 0`, insert exactly one `Trade` sized to `abs(delta)`.

v1 scope restriction: the adjustment trade only ever picks `BUY` (delta > 0) or `SELL` (delta < 0) — never `SHORT`/`COVER`. If reconciling the delta would cross zero into a short position (or the Schwab-reported quantity is itself negative), the row is flagged "manual review needed" in the view rather than auto-adopted. `TradeType.SHORT`/`COVER` exist (`trade.py:31-38`) but silently picking one to force a match is exactly the kind of "hidden mutation" this page exists to prevent.

Fields on the trade record, and why each is new: `Trade` today (`trade.py:40-89`) has no field that marks a row as machine-generated. Adding, all nullable/defaulted so existing rows are unaffected:
- `source` (String(50), default `"manual"`) — mirrors `broker_import`'s `source` convention; distinguishes `manual` from `schwab_api` (and later `csv_import`, sub-PR 3). Note this is provenance, not "syntheticness": sub-PR 3's CSV import will write *real* historical fills sourced from a broker file — those get `source="csv_import"` but are not synthetic.
- `is_synthetic` (Boolean, default `False`) — true only for a delta-adjustment/synthetic-opening trade. Orthogonal to `source`.
- `basis_is_estimated` (Boolean, default `False`) — see [§3](#3-basis-math-fifo-remaining-lots-not-net-cash).
- `source_import_run_id` (nullable FK `broker_import_runs.id`, `ON DELETE SET NULL`) — the idempotency/provenance key, see below.

**Idempotency:** re-running adoption for the same `(account_id, equity)` against the *same* `BrokerImportRun` must not duplicate. Enforce via a partial unique index on `(user_id, account_id, equity_id, source_import_run_id) WHERE is_synthetic`. A later Schwab pull that produces a *new* `BrokerImportRun` with further drift is allowed to create a second adjustment trade — adoption is "reconcile against the latest snapshot," not "one-time stamp."

**Transaction boundaries:** reuse `TradeService.create_trade` (`trade.py:121-183`) as-is rather than inventing a new commit path — it already does insert → commit → `_recalculate_pairs` (which commits again, `trade.py:424-549`) in the same two-commit shape every manual trade goes through. Adoption's only new work is passing the provenance fields through `TradeCreate`.

**Edit/delete policy (binding on amendment 1 — Trade is mutable, not append-only):** `update_trade` (`trade.py:185-237`) and `delete_trade` (`trade.py:239-256`) both already recalculate pairs after mutating, via `PUT`/`DELETE /api/v1/trades/{trade_id}` (`endpoints/trade.py:226-273`). Delete is allowed unchanged — deleting a synthetic trade just removes the plug and recalculates; the user can re-run adoption to regenerate it. Edit of `quantity`/`price`/`trade_type`/`executed_at` on a row where `is_synthetic=True` must be rejected (422) by `update_trade` unless the caller first "detaches" the trade (an explicit action that clears `is_synthetic`/`source_import_run_id`, turning it into an ordinary manual trade). Rationale: if a hand-edit were allowed in place, the row would silently drift from what adoption computed while still claiming (via `source_import_run_id`) to satisfy the idempotency key — a later re-run against unchanged Schwab data would see "already adopted for this run" and never re-heal it, so the stale hand-edit persists invisibly.

**Alternatives considered:**
- *Synthetic-opening only (ignore existing trades, always write one trade for the full Schwab quantity).* Rejected as the general mechanism — it silently discards real trade history (timing, realized P&L) whenever the user already has some organic trades for that equity, which is exactly the case the delta form handles for free. Kept as the degenerate case.
- *Notes-field convention* (encode "SYNTHETIC" in `Trade.notes`) — explicitly rejected per amendment 4: not queryable, not enforceable, not a real idempotency key.

**Consequences:** requires a schema migration (new `Trade` columns + partial unique index) and a `TradeService` change (the detach-before-edit guard). Neither ships in this brief — this is the design the next-wave migration follows.

- [ ] RATIFIED / - [ ] AMENDED: ___

## 3. Basis math: FIFO-remaining-lots, not net-cash

**Recommendation: "IC basis" for reconciliation purposes is the weighted-average price of still-open FIFO lots, computed by extending the existing FIFO walk — never `PositionSummary.avg_cost_basis`.**

`_calculate_positions` (`trade.py:551-669`) computes `avg_cost_basis` as `abs(total_cost / net_quantity)` (`trade.py:602-617`), where `total_cost` is a running *net-cash* figure: `+= qty*price + fees` on a buy/cover, `-= qty*price - fees` on a sell/short (`trade.py:608-614`). This is not a cost-basis in the tax-lot sense. After a profitable partial sale, the subtracted sale proceeds can drive `total_cost` toward zero or negative, and `avg_cost_basis` for the *remaining* shares becomes meaningless (or the `abs()` masks a negative number into a positive-looking one). Comparing that figure directly to Schwab's `average_price` (`ImportedPosition.average_price`, `broker_import.py:188`) would produce a basis-delta that is not just approximate but actively wrong in the common "trimmed a winner" case. **This design prohibits that comparison.**

The FIFO walk in `_recalculate_pairs` (`trade.py:424-549`) already computes exactly the right number and throws it away: it maintains `long_queues`/`short_queues` keyed by `account_id` (`trade.py:454-455`), and every unmatched entry left in a queue at the end of the walk *is* the open-lot state — `(trade_id, remaining_qty, price, executed_at, fee_per_share)`. Today that leftover queue is discarded once the loop ends; recommendation is a small, additive read-only helper (e.g. `TradeService._get_open_lots(user_id, equity_id, account_id)`) that runs the identical walk and returns the leftover queues instead of dropping them. `ic_basis = sum(remaining_qty * price) / sum(remaining_qty)` over the open long (or short) queue. This is not new algorithm design — it's the same loop with a different return value — but it is new code, out of scope for this docs-only brief.

**Basis source for the synthetic/adjustment trade itself:** use `ImportedPosition.average_price` when present. It is `Optional[Decimal]` in the model (`broker_import.py:188`) — Schwab does not always return it. When null, fall back to the equity's current quote price at adoption time (already available via `EquityService`) and set `basis_is_estimated=True` on the trade (§2) so the reconciliation view and any future audit can distinguish a broker-reported basis from a market-price placeholder.

**Alternatives considered:**
- *Use `avg_cost_basis` as-is (it's already computed, zero new code).* Rejected — it's the wrong number, per the mutability finding above; shipping a reconciliation view that compares it against Schwab's basis would produce false "drift" alerts for any account with a realized gain.
- *User-supplied basis at adoption time.* Rejected as the default (adds a manual-entry step to what should be a one-click adoption) but kept available as a per-row override in the eventual adoption UI, since Schwab's `average_price` semantics (does it include fees? realize adjustments for wash sales?) aren't independently verifiable from the API alone — see [what the CSV specimens would firm up](#what-the-csv-specimens-would-still-firm-up).

**Consequences:** the reconciliation view's basis-delta column has a real prerequisite — the open-lots helper — that quantity reconciliation does not. Recommendation in [§6](#6-the-read-only-reconciliation-view-the-buildable-slice) is to ship both in the same next-wave ticket rather than sequence them, since the helper is small and self-contained.

*Note on `fifo-matching.md`: that page's "Edge cases and known gaps" section currently claims fees are ignored in realized P&L and that no account partitioning or tests exist. All three claims are stale — `_recalculate_pairs` nets both legs' commissions into `realized_pnl` (`trade.py:474-480`, `:520-523`), partitions FIFO queues by `account_id` (`trade.py:454-455`), and `backend/tests/test_services/test_trade_positions.py` covers exactly that partitioning. This brief does not edit `fifo-matching.md` (out of scope per the ticket) — every claim above is grounded directly in the current `trade.py`/tests, not in that page. Fixing `fifo-matching.md` is flagged as a follow-up in the PR description.*

- [ ] RATIFIED / - [ ] AMENDED: ___

## 4. Account-hash ↔ account mapping lifecycle

**Recommendation: linking is user-initiated and one-directional (hash → account); hash rotation is never auto-migrated; orphaning is a status flag, never a delete; re-linking to an account that already holds trades requires an explicit confirmation.**

Schwab mints the `account_hash` specifically so the real account number never has to leave their systems (`schwab.py:69-84`'s `redact_account_fields` docstring), and nothing in the ingested payloads carries a stable secondary identifier (routing/mask/nickname) that would let this codebase detect "hash `A` and hash `B` are the same physical account after a rotation." That is a hard boundary, not a gap to code around: **automatic rotation migration is prohibited.**

Lifecycle, using the `AccountLink` entity from [§1](#1-what-model-is-adopted-into):
- **New hash appears** (returned by `get_account_hashes()` with no matching `AccountLink` row for this user): shown as unlinked; user links it to an existing `Account` or creates a new one. `AccountLink.status = active`.
- **A previously-linked hash stops appearing:** its `AccountLink.status` flips to `orphaned` (never deleted — deleting would sever provenance for no reason; every adoption `Trade` already carries its own `account_id` directly, captured at creation time in §2, so orphaning a link never retroactively changes past adoption trades). The UI surfaces this as a warning on the linked `Account`: "this Schwab connection no longer sees this account — data may be stale or the account was closed/moved." No new pulls happen for an orphaned hash.
- **User re-links** (either the same hash reappearing, or a genuinely new hash for what the user says is the same real account): if the target `Account` already has trades (manual or prior-adopted), require an explicit confirmation step before allowing the link — "This account already has N trades. Linking will treat all of them as this account's baseline for future reconciliation." This is the one place amendment 6 requires a confirmation, and it's the right place: it's the only step where mis-linking could make an *unrelated* account's real trade history participate in a delta calculation it has nothing to do with.

**What detects orphaning in the first place:** `get_account_hashes()` is only called during whatever process discovers hashes; it is not itself persisted anywhere today, and `schwab_ingestion.py`'s module docstring is explicit that "NO API endpoint/UI" exists yet for anything beyond the raw pull. This brief does not resolve *when* that discovery call runs (e.g., piggybacking on the same cadence as `pull_positions`, or a dedicated periodic job) — that's an orchestration decision for whoever builds the linking UI, not a semantics question this page needs to pin. Flagging it here so it isn't silently assumed solved.

**Alternatives considered:**
- *Match by symbol overlap or balance similarity when a hash disappears and a new one appears close in time.* Rejected — heuristic account-matching is exactly the kind of silent, unverifiable behavior amendment 6 rules out; a wrong auto-match would misattribute real trade history.
- *Delete the `AccountLink` row on orphaning.* Rejected — see above; nothing is gained and it discards the "this Account used to be Schwab-linked" signal that explains why old adoption trades exist.

**Consequences:** the linking UI is a real, non-trivial surface (unlinked-hash list, link/create flow, orphan warnings, re-link confirmation) — bigger than the read-only view in §6. It's the correct prerequisite for adoption, but not for the view alone; see §6 for what can ship without it.

- [ ] RATIFIED / - [ ] AMENDED: ___

## 5. Asset-class eligibility

**Recommendation: v1 adoption eligibility is `ImportedPosition.asset_type == "EQUITY"` (Schwab's raw value) only. Ineligible rows stay visible in the reconciliation view, flagged non-adoptable — never silently dropped.**

`_normalize_position` (`schwab_ingestion.py:190-201`) preserves Schwab's `instrument.assetType` verbatim into `ImportedPosition.asset_type` (`broker_import.py:174`, comment at `:172-173`: "Raw Schwab instrument.assetType (EQUITY, OPTION, MUTUAL_FUND, ...). Unrecognized/future values are stored as-is, never dropped"). IC's own `Trade`/`Equity` model has no representation for an options contract (strike, expiry, contract multiplier) or a fund share class — `Equity.asset_type` (`backend/app/db/models/equity.py:24`) is a free-form string that today only distinguishes things like "stock" vs. ETF-ish securities, not a real type system, and there is nothing anywhere in the domain model an adopted OPTION or MUTUAL_FUND position could be written into. Restricting adoption to equities isn't a policy choice so much as the only thing the schema can currently hold.

**Alternatives considered:**
- *Widen `Equity`/`Trade` to support options/funds in the same pass.* Rejected as out of scope — that's a materially larger schema and P&L-math change (option Greeks, expiry-driven realized-vs-unrealized rules) that has nothing to do with pinning adoption semantics for the common case.
- *Silently omit ineligible rows from the view.* Rejected per amendment 5 explicitly — a user with an options position at Schwab needs to see "this exists at your broker and isn't reconcilable yet," not have it vanish, which would look like a data-loss bug rather than a known limitation.

**Consequences:** the reconciliation view (§6) always renders every `ImportedPosition` row for the linked account, with an `eligible` boolean and (when false) a short reason string ("asset_type OPTION not supported").

- [ ] RATIFIED / - [ ] AMENDED: ___

## 6. The read-only reconciliation view — the buildable slice

**Recommendation: `GET /api/v1/accounts/{account_id}/reconciliation`, gated only on an active `AccountLink` for that account — not on the Trade-provenance schema from §2/§3, which is only needed once adoption becomes a mutation.**

This is the deliberate scope cut that makes something shippable next wave without waiting for the full adoption mutation: quantity reconciliation needs nothing beyond `AccountLink` (§1) plus data that already exists (`_calculate_positions(by_account=True)` and `ImportedPosition`). Basis reconciliation additionally needs the open-lots helper from §3 (small, same-ticket-sized). Neither needs the `Trade` provenance columns or the adoption endpoint from §2 — those are prerequisites for the *mutation* (a later wave), not the view.

**Shape**, one row per symbol present on either side (union of the linked hash's latest-complete-run `ImportedPosition` rows and IC's per-`account_id` positions for that account):

```text
GET /api/v1/accounts/{account_id}/reconciliation
{
  symbol: str
  asset_type: str                 # Schwab's raw instrument.assetType
  eligible: bool                  # asset_type == "EQUITY" (§5)
  ineligible_reason: str | null

  schwab_quantity: Decimal | null
  ic_quantity: Decimal | null
  quantity_delta: Decimal | null  # null when either side has no position at all

  schwab_basis: Decimal | null    # ImportedPosition.average_price
  ic_basis: Decimal | null        # FIFO-remaining-lot helper (§3); null until that helper ships
  basis_delta: Decimal | null     # same guard — never derived from avg_cost_basis (§3)

  last_import_at: datetime        # latest COMPLETE run's created_at (schwab_ingestion.get_latest_complete_run)
  newer_failed_import_at: datetime | null  # a run newer than last_import_at with status=failed, if any
}
```

`last_import_at` comes straight from `get_latest_complete_run` (`schwab_ingestion.py:392-412`), which already exists. `newer_failed_import_at` does not exist yet as a helper — recommend a small sibling read function (same read-only, any-session contract as `get_latest_complete_run`) that finds the latest run of *any* status and returns its `created_at` only when it's newer than the latest complete run and `status == FAILED`. This is what surfaces "your last pull attempt actually failed, don't trust that this is current" (amendment 7) without conflating a failed run with a complete one on the `BrokerImportRun` model itself (`broker_import.py:51-58`'s `ImportStatus` already separates them cleanly; this is just a second query, not a schema change).

**Page:** a new tab/section on the account's existing management surface (`frontend/src/components/trade/AccountManager.tsx`, alongside the existing Schwab connection UI in `frontend/src/app/settings/page.tsx` / `frontend/src/lib/hooks/useSchwab.ts`) rendering this as a table, one row per symbol, with the `eligible=false` rows visibly greyed/flagged rather than hidden. No "Adopt" mutation button in this slice — an `adopted`/`has_synthetic_trade` indicator column is deliberately left out of the shape above, since it would require the §2 `Trade` provenance columns to compute; add it once the mutation endpoint exists.

**Alternatives considered:**
- *A global `GET /api/v1/schwab/reconciliation` across all linked accounts at once.* Kept as a plausible follow-up (a portfolio-wide "everything that needs attention" view), but per-account is the right first slice — it matches the existing per-account positions call shape (`GET /api/v1/trades/portfolio?by_account=true`) and doesn't require deciding a cross-account aggregation format up front.
- *Ship basis reconciliation gated on the open-lots helper landing first, as a hard blocking dependency in a separate ticket.* Rejected — the helper is small enough (same walk, different return) to build in the same ticket as the view; sequencing it as a separate blocking dependency just adds a wave of latency for no isolation benefit.

**Consequences:** this is the next AI-able ticket once §1-§5 are ratified: `AccountLink` migration + model + a minimal link/list endpoint, the open-lots helper, and the reconciliation GET endpoint + page. Still no mutation, no OAuth changes, no Schwab API calls beyond what PR #216 already added.

- [ ] RATIFIED / - [ ] AMENDED: ___

## Demo-guard

**Recommendation: every adoption-related *mutation* endpoint gets `_demo_guard: None = Depends(require_not_demo)` as its first dependency parameter, matching the existing convention exactly; the read-only reconciliation view in §6 gets no demo guard at all.**

`require_not_demo` (`backend/app/core/dependencies.py:184-195`) raises `403` when `is_demo_mode()` (`backend/app/core/demo.py:6-7`) is true. `is_demo_mode()` reads a single server-wide `settings.DEMO_MODE` flag (`backend/app/core/config.py:166`) — it is not per-user. This is the identical pattern already used on every other mutating endpoint touching trades, accounts, and Schwab: `POST/PUT/DELETE /api/v1/trades*` (`endpoints/trade.py:84,230,258`), `POST/PUT/DELETE /api/v1/accounts*` (`endpoints/account.py`), and `POST /connect` / `GET /callback` / `DELETE /disconnect` on the Schwab OAuth router (`endpoints/schwab.py`, whose module docstring states the convention outright: "Mutations are demo-blocked; status is read-only and safe").

Apply the same dependency to: linking/unlinking an `AccountLink` (§1/§4), and the future adoption-trigger endpoint (§2). The §6 `GET /api/v1/accounts/{account_id}/reconciliation` endpoint is read-only and gets no guard, matching every other `GET` in this codebase (including `GET /schwab/status`, which is explicitly called out as safe in demo mode) — a demo user can see what an adoption *would* do without being able to execute it.

**Consequences:** none beyond the endpoint boilerplate — this is a "do what everything else already does" recommendation, not a new pattern.

- [ ] RATIFIED / - [ ] AMENDED: ___

## Ratification

All six questions above, plus demo-guard, need Andrew's checkbox before any of this is buildable:

- [ ] §1 What model is adopted into — RATIFIED / AMENDED: ___
- [ ] §2 Synthetic-opening vs. delta-adjustment — RATIFIED / AMENDED: ___
- [ ] §3 Basis math — RATIFIED / AMENDED: ___
- [ ] §4 Account-hash ↔ account mapping lifecycle — RATIFIED / AMENDED: ___
- [ ] §5 Asset-class eligibility — RATIFIED / AMENDED: ___
- [ ] §6 Reconciliation view slice — RATIFIED / AMENDED: ___
- [ ] Demo-guard — RATIFIED / AMENDED: ___

Once all seven are checked, §6's endpoint + `AccountLink` migration + the open-lots helper is a chartable next-wave ticket on its own; §2's `Trade` provenance migration and the adoption mutation endpoint are the wave after that.

### What the CSV specimens would still firm up

The U12-3 redacted broker-CSV specimens (still owed by Andrew, tracked separately in §4 of the wave roadmap) are **not** a blocker for ratifying any of the above — every recommendation here is grounded in the live Schwab API contract already landed in PR #216, not in CSV shape. Where specimens would sharpen field-level detail once they exist:
- Whether Schwab's `average_price` (§3) is fee-inclusive, and whether a wash-sale or corporate-action adjustment ever changes it retroactively between pulls — currently unverifiable from the position-snapshot API alone, since `ImportedPosition` rows are never updated in place (`broker_import.py:146-153`).
- Real-world `assetType` values beyond `EQUITY`/`OPTION`/`MUTUAL_FUND` that Schwab actually returns for this account (the model comment lists these as examples, not an exhaustive enum) — firms up the `ineligible_reason` strings in §6's view.
- Whether CSV-imported (sub-PR 3) trade rows will carry Schwab's own transaction-level fee/commission breakdown in a way `_fee_per_share` (`trade.py:33-45`) can consume directly, which would matter if a future basis recommendation ever wants to use transaction history instead of the position snapshot's `average_price`.
