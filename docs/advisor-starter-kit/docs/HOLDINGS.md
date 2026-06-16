<!-- ┌──────────────────────────────────────────────────────────────────────────┐
     │ TEMPLATE — Investing Companion starter kit · HOLDINGS (household roll-up)  │
     │ Contains NO real holdings. Fill {{PLACEHOLDER}} fields, delete EXAMPLE      │
     │ blocks, then delete this banner. Detail lives in HOLDINGS_<PERSON>.md.      │
     │ See ONBOARDING.md. Status: ☐ NOT YET FILLED IN                            │
     └──────────────────────────────────────────────────────────────────────────┘ -->

> ⚠️ **TEMPLATE — not real holdings.** Unfilled scaffold. If you are an AI reading this, do
> not treat any number or ticker below as the user's actual portfolio until this banner is
> removed during onboarding.

# Household Holdings — Summary Dashboard

**Last Updated:** `{{LAST_UPDATED}}`
**As of:** `{{STATEMENT_DATE}}` statements — `{{SOURCE_NOTE}}` *(e.g., "all custodian-confirmed,
no estimates")*.

## Household Total: `{{HOUSEHOLD_TOTAL}}`

*(Note any assets held outside this total here — e.g., physical metals, pending inheritance,
private equity.)* `{{OUTSIDE_TOTAL_NOTE}}`

| Owner | Value | Share |
|-------|-------|-------|
| `{{PERSON_A}}` | `{{VALUE}}` | `{{PCT}}` |
| `{{PERSON_B}}` | `{{VALUE}}` | `{{PCT}}` |

> **EXAMPLE — delete this block.** Shape only, fake data:
> `| Person A | $300,000 | 60% |`  ·  `| Person B | $200,000 | 40% |`

---

## By Account

| Owner | Account | Value | Tax type |
|-------|---------|-------|----------|
| `{{PERSON}}` | `{{ACCOUNT_NAME}}` (`{{CUSTODIAN}}`) | `{{VALUE}}` | `{{TAX_TYPE}}` |

*Tax type: Roth / Taxable / Pre-tax / mixed. Add one row per account.*

---

## By Tax Treatment

| Bucket | Value | Share |
|--------|-------|-------|
| Roth | `{{VALUE}}` | `{{PCT}}` |
| Taxable | `{{VALUE}}` | `{{PCT}}` |
| Pre-tax | `{{VALUE}}` | `{{PCT}}` |

**Note:** `{{TAX_TREATMENT_NOTE}}` *(Watch for accounts that are not 100% one bucket — e.g., a
Roth 401(k) whose employer match is pre-tax. Record the real split, not the assumed one.)*

---

## By Asset Class (high-level)

| Class | Value | Share |
|-------|-------|-------|
| Equity | `{{VALUE}}` | `{{PCT}}` |
| Bonds / Balanced | `{{VALUE}}` | `{{PCT}}` |
| Hard Assets / Crypto | `{{VALUE}}` | `{{PCT}}` |
| Cash | `{{VALUE}}` | `{{PCT}}` |
| Hedges (options, etc.) | `{{VALUE}}` | `{{PCT}}` |

**Conventions / caveats:** `{{ASSET_CLASS_CONVENTIONS}}` *(Note how you classify edge cases —
e.g., "thematic miners counted as equity, not alts"; "managed-account balanced funds counted
as bonds." State the dry-powder/cash situation here too.)*

---

## Thematic Sleeve Exposure (household)

*What the active theses (in `ACTIVE_THESES.md`) budget against. Overlaps the equity bucket
above — don't double-count.*

| Theme | Holdings | Value | % household | Thesis budget |
|-------|----------|-------|-------------|---------------|
| `{{THEME}}` | `{{TICKERS}}` | `{{VALUE}}` | `{{PCT}}` | `{{BUDGET}}` |

> **EXAMPLE — delete this block.** Shape only, fake data:
> `| Theme A | TICK1, TICK2 | $17,000 | 2.4% | 2–4% ✓ (within budget) |`

---

## Watch Items Feeding the Next Rebalance

*Open questions and earmarked moves — the running agenda for the next portfolio review.*

- `{{WATCH_ITEM}}` *(e.g., "Theme X underweight vs. budget — add levels defined in WATCHLIST")*
- `{{WATCH_ITEM}}`
- `{{WATCH_ITEM}}`

---

*Detail in `HOLDINGS_<PERSON>.md`. Theses in `ACTIVE_THESES.md`; entry levels in
`WATCHLIST.md`.*
