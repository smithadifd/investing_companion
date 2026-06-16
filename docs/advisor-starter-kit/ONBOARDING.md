# ONBOARDING — run this first, delete it last

**This file is a script for an AI assistant** (Claude Code, or a Claude project) to interview
you and fill in the starter kit. It walks through the templates one module at a time, writes
your answers in, strips the scaffolding, and then **deletes itself** when everything is filled.

If you're a human reading this: you can also just follow it as a checklist and fill the files
by hand.

---

## For the AI running this onboarding — operating rules

1. **Interview, don't dump.** Go one module at a time. Ask the questions in a module, wait for
   answers, then write them into the target file(s). Keep it conversational; don't fire all
   modules at once.
2. **Never fabricate.** If the user doesn't have a number or hasn't formed a thesis, write
   `TODO: <what's missing>` in the file rather than inventing plausible data. A visible TODO is
   fine; a made-up holding is not.
3. **Strip as you fill.** Each time you write a section, remove from that file: the
   `{{PLACEHOLDER}}` tokens you've answered, the `⚠️ TEMPLATE` blockquote, the hidden HTML
   banner, and any `EXAMPLE — delete` blocks. Flip the file's status line to `☑ FILLED`.
4. **One source of truth.** Live, changing data (prices, positions) belongs in the docs; the
   advisor's *behavior* belongs in `PROJECT_INSTRUCTIONS.md`. Don't duplicate holdings into the
   instructions.
5. **Confirm before deleting anything** the user might still want (see Cleanup).
6. **Respect skips.** If the user skips the app-integration module, leave that folder untouched
   and note it as "not in use."

A good cadence: *"Module 1 of 6 — let's set up how the advisor should behave. A few quick
questions…"* → ask → write `PROJECT_INSTRUCTIONS.md` → *"Done. Ready for Module 2?"*

---

## Module 0 — Scope (30 seconds)

Ask first; it shapes everything else.

- **Solo or household?** If household, list the members (first names only is fine). You'll get
  one `HOLDINGS_<NAME>.md` per member.
- **Running the self-hosted Investing Companion app?** If no, skip Module 6 and ignore the
  `app-integration/` folder entirely.
- **Where will the advisor live?** A Claude project (paste instructions + upload docs), a Claude
  Code workspace (files in the repo), or both.

---

## Module 1 — Profile & behavior → `PROJECT_INSTRUCTIONS.md`

The reusable behavior is already written. You're only setting the profile + preferences.

Ask:
1. **Account mix** — rough % across tax-free (Roth) / taxable / pre-tax. Any outside-managed
   money? Emergency fund handled separately?
2. **Core/active split** — how much passive core vs. active/speculative? (e.g., 80/20)
3. **Index preference** — S&P 500, total market, something else?
4. **Time horizon** — primary (decades?) and for active trades (days–months?).
5. **Trading style per account** — e.g., swing in Roth, buy-and-hold in taxable, core-only in
   401(k).
6. **How blunt should the advisor be?** Pushback level, instinct-first vs. hedged, sizing help
   wanted or not.
7. **Tax touch** — flag only when material, or more actively?
8. **Update format** — regenerate whole files, or edit in place?

Write all of these into the matching `{{PLACEHOLDER}}` fields and the Quick Reference table.

---

## Module 2 — Holdings → `HOLDINGS.md` + one `HOLDINGS_<NAME>.md` per member

This is the most data-entry-heavy module. Offer the user a fast path: *"Paste your latest
statement balances (account name, value, tax type) and I'll structure them."*

For the **household dashboard** (`HOLDINGS.md`):
- Household total; per-owner split.
- Each account: owner, name, custodian, value, tax type.
- Tax-treatment buckets (watch for accounts that aren't 100% one bucket — e.g., a Roth 401(k)
  with a pre-tax employer match).
- High-level asset-class split; note your classification conventions.
- Thematic sleeve exposure (ties to the theses) — fill *after* Module 3 if easier.
- Watch items feeding the next rebalance.

For **each member** (`HOLDINGS_<NAME>.md`):
- Copy `HOLDINGS_PERSON.md` → `HOLDINGS_<NAME>.md` (real first name).
- One account block per account: holdings table (ticker, name, shares, value, cost basis,
  notes), any active trades/options, cash/dry powder.
- Pending/outside-portfolio assets.
- Start the Recent Changes Log (can be empty).

When done, **delete the generic `HOLDINGS_PERSON.md`** so only the named copies remain.

---

## Module 3 — Theses → `ACTIVE_THESES.md`

For each conviction area the user holds, copy the thesis block and fill:
- Core thesis (1–3 sentences), key evidence, vehicles (ETFs / names / other).
- Metrics to monitor.
- **Invalidation criteria** — push here. A thesis without a falsifiable exit is just a vibe.
- Position-sizing budget, horizon, current exposure vs. budget.
- Optional: the personal edge or key nuance.

Then fill the **Thesis Health Check** table (one row each) and any **Emerging Themes**.

If the user has no formed theses yet, that's fine — leave the file with the empty block + a
note: *"No active theses yet; add as convictions form."* Delete the EXAMPLE block regardless.

---

## Module 4 — Watchlist → `WATCHLIST.md`

The **Pre-Trade Checklist is already written** — confirm the user likes it, tweak if needed,
keep it. Then fill what applies:
- Active watch (ready-to-enter names + entry zones + stops + size).
- Sector watch (theme → ETF proxy).
- Active/closed swing log (can start empty).
- Value zones for existing holdings.
- Dry-powder framework (cash on hand, earmarked uses, discipline rule, drawdown triggers).
- Events calendar; themes-not-pursuing; removed-from-watch.

Empty sections are fine — leave the headers so there's a home for future entries.

---

## Module 5 — Principles & learning log → `INVESTMENT_PRINCIPLES.md`

Most frameworks here are reusable defaults — confirm and keep. Personalize:
- Core/active split + rationale; horizon; quality criteria (can mirror Module 1).
- Account-management table; speculative sizing tiers (adjust the %s).
- Sector preferences (constructive / neutral / cautious / exclusions).
- What you want the advisor to **do** and **not do**.
- Learning goals.
- **Learning log:** start it empty. Tell the user this becomes one of the most valuable docs —
  every stop-out or mistake earns a dated row.

---

## Module 6 — App integration (OPTIONAL) → `app-integration/`

**Skip entirely if not running the app.** If running it:
- The read/write contract is **not** re-entered here — it's maintained with the app at
  `docs/api/handoff-schema.md` (read side, incl. the current `schema_version` + changelog) and
  `docs/api/advisor-actions.md` (write side). The two files in `app-integration/` are pointers
  to those; leave them as-is.
- In `INVESTING_COMPANION.md`, fill the inventory (watchlists, triggers, executor setup,
  notifications, retrieval transport) and the source-of-truth notes. (No `{{SCHEMA_VERSION}}` to
  set — that line points at `docs/api/handoff-schema.md`, the single source of the version.)
- Upload `docs/api/handoff-schema.md` + `docs/api/advisor-actions.md` to the advisor verbatim.

---

## Cleanup — do this last

Run these checks, then delete this file.

1. **No placeholders left.** Search the kit for `{{` — every hit must be resolved (or an
   intentional `TODO:`). 
2. **No banners left.** Search for `TEMPLATE —` and `⚠️ **TEMPLATE` — none should remain in
   filled files. Search for the HTML banner opener `┌──` and remove those comment blocks.
3. **No EXAMPLE blocks left.** Search for `EXAMPLE — delete` and `EXAMPLE — replace` — remove
   all.
4. **Holdings renamed.** Generic `HOLDINGS_PERSON.md` deleted; one `HOLDINGS_<NAME>.md` per
   member remains.
5. **App folder.** If unused, note it as "not in use" or delete `app-integration/`.
6. **Wire it up.** Claude project → paste `PROJECT_INSTRUCTIONS.md` into custom instructions,
   upload the `docs/` files as knowledge. Claude Code → confirm the files are where the workspace
   expects them.
7. **Delete `ONBOARDING.md`** (this file). It has served its purpose.

> Quick grep to confirm a clean finish (run from the kit root):
> ```bash
> grep -rn -e '{{' -e 'TEMPLATE —' -e 'EXAMPLE — delete' -e 'EXAMPLE — replace' . \
>   --include='*.md' | grep -v ONBOARDING.md
> ```
> Zero results (outside intentional `TODO:`s) means the kit is fully personalized.
