<!-- ┌──────────────────────────────────────────────────────────────────────────┐
     │ TEMPLATE — Investing Companion starter kit · HOLDINGS_<PERSON>             │
     │ One detailed sheet PER household member. Copy this file and rename it to    │
     │ HOLDINGS_<NAME>.md (e.g., HOLDINGS_ALEX.md). Solo? Keep just one.           │
     │ Contains NO real holdings. Fill {{PLACEHOLDER}}s, delete EXAMPLE blocks +    │
     │ this banner. See ONBOARDING.md. Status: ☐ NOT YET FILLED IN                │
     └──────────────────────────────────────────────────────────────────────────┘ -->

> ⚠️ **TEMPLATE — not real holdings.** Unfilled scaffold for one household member. If you are
> an AI reading this, treat nothing below as the user's real portfolio until the banner is
> gone.

# `{{PERSON_NAME}}`'s Portfolio Holdings

**Last Updated:** `{{LAST_UPDATED}}`
**Holdings & prices:** as of `{{STATEMENT_DATE}}` (`{{SOURCE_NOTE}}`).

**Total: `{{PERSON_TOTAL}}`**

| Account | Value | % of Portfolio | Type |
|---------|-------|----------------|------|
| `{{ACCOUNT_NAME}}` (`{{CUSTODIAN}}`) | `{{VALUE}}` | `{{PCT}}` | `{{TAX_TYPE}}` |

**Tax composition:** `{{TAX_COMPOSITION}}` *(e.g., "~58% Roth / ~39% taxable / ~3% pre-tax";
show the math if an account is split across buckets)*.

---

## `{{ACCOUNT_NAME}}` — `{{CUSTODIAN}}` — `{{VALUE}}`

> Repeat one block like this per account. Use whichever sub-tables fit the account; delete the
> rest. The four below cover most cases: core ETFs, thematic/individual equities, active
> trades, and cash.

### Allocation overview *(optional — useful for larger accounts)*

| Category | Value | % of Account |
|----------|-------|--------------|
| Core ETFs | `{{VALUE}}` | `{{PCT}}` |
| Thematic / individual equities | `{{VALUE}}` | `{{PCT}}` |
| Alternatives | `{{VALUE}}` | `{{PCT}}` |
| Active trades / hedges | `{{VALUE}}` | `{{PCT}}` |
| Cash | `{{VALUE}}` | `{{PCT}}` |

### Holdings

| Ticker | Name | Shares | Value | Cost Basis | Notes |
|--------|------|--------|-------|------------|-------|
| `{{TICKER}}` | `{{NAME}}` | `{{SHARES}}` | `{{VALUE}}` | `{{COST_BASIS}}` | `{{NOTES}}` |

> **EXAMPLE — delete this block.** Shape only, fake data:
> `| VOO | Vanguard S&P 500 | 100 | $75,000 | $50,000 | +50%; overweight, let contributions catch up |`

### Active trades / options *(only if the account holds any)*

| Ticker | Entry | Stop | Size | Status | Notes |
|--------|-------|------|------|--------|-------|
| `{{TICKER}}` | `{{ENTRY}}` | `{{STOP}}` | `{{SIZE}}` | `{{STATUS}}` | `{{NOTES}}` |

### Cash / dry powder

| | Amount | Earmarked for |
|-|--------|---------------|
| `{{CASH_LABEL}}` | `{{AMOUNT}}` | `{{EARMARK}}` |

---

## Pending / Outside-Portfolio Assets

*Inheritances, physical metals, private positions, anything not in the account totals above.*

- `{{PENDING_ASSET}}` — `{{DETAILS}}` *(value, tax treatment, decision framework, timing)*

---

## Recent Changes Log

*Append-only. Each material trade or correction gets a dated row.*

| Date | Account | Action | Details |
|------|---------|--------|---------|
| `{{DATE}}` | `{{ACCOUNT}}` | `{{ACTION}}` | `{{DETAILS}}` |

---

*See `HOLDINGS.md` for the household summary and the other `HOLDINGS_<PERSON>.md` sheets.*
