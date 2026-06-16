<!-- ┌──────────────────────────────────────────────────────────────────────────┐
     │ TEMPLATE — Investing Companion starter kit · WATCHLIST                     │
     │ Entry frameworks, swing log, dry-powder plan, calendar. The Pre-Trade       │
     │ Checklist is a ready-to-use default — keep or tweak it. Contains NO real     │
     │ positions. Fill {{PLACEHOLDER}}s, delete EXAMPLE blocks + this banner.       │
     │ See ONBOARDING.md. Status: ☐ NOT YET FILLED IN                            │
     └──────────────────────────────────────────────────────────────────────────┘ -->

> ⚠️ **TEMPLATE — not real positions.** Unfilled scaffold. If you are an AI reading this, treat
> nothing below as the user's actual watchlist or trades until the banner is removed.

# Watchlist

**Last Updated:** `{{LAST_UPDATED}}`

> Prices embedded here go stale — re-verify live before acting.

---

## Active Watch — Ready to Enter

*Thesis confirmed; waiting on an entry point.*

| Ticker | Name | Sector / Thesis | Target Entry | Current | Stop | Position Size |
|--------|------|-----------------|--------------|---------|------|---------------|
| `{{TICKER}}` | `{{NAME}}` | `{{THESIS}}` | `{{ENTRY_ZONES}}` | `{{PRICE}}` | `{{STOP}}` | `{{SIZE}}` |

> **EXAMPLE — delete this block.** Shape only, fake data:
> `| TICK | Example Co. | Theme A | $50–52 starter / $47–48 add | ~$55 | thesis-based or $47.50 | 10–15 sh, build to 40 |`

---

## Sector Watch

*Broad themes monitored via ETF proxies.*

| Sector / Theme | ETF Proxy | Status | Key Drivers | Names of Interest |
|----------------|-----------|--------|-------------|-------------------|
| `{{THEME}}` | `{{ETF}}` | `{{STATUS}}` | `{{DRIVERS}}` | `{{NAMES}}` |

---

## Active Swing Trades

*Running log. The user brings the chart + setup; the advisor runs the pre-trade checklist below.*

| Ticker | Entry Date | Entry | Size | Stop | Target | Setup | Status |
|--------|-----------|-------|------|------|--------|-------|--------|
| `{{TICKER}}` | `{{DATE}}` | `{{PRICE}}` | `{{SIZE}}` | `{{STOP}}` | `{{TARGET}}` | `{{SETUP}}` | `{{STATUS}}` |

### Closed Swings

| Ticker | Entry | Exit | Size | P/L | Duration | Lesson |
|--------|-------|------|------|-----|----------|--------|
| `{{TICKER}}` | `{{ENTRY}}` | `{{EXIT}}` | `{{SIZE}}` | `{{PL}}` | `{{DAYS}}` | `{{LESSON}}` |

*Note: when a closed swing teaches something, also record it in `INVESTMENT_PRINCIPLES.md`'s
learning log.*

---

## Pre-Trade Checklist (advisor runs this)

*Reusable as-is. The user brings the chart and setup; the advisor runs these six points; both
agree before entry.*

1. **Earnings proximity** — earnings within ~2 weeks? If yes, flag binary-event risk: exit
   before, or consciously accept gap risk.
2. **Thesis alignment** — does the technical setup line up with an active thesis? Technicals +
   fundamentals aligned = highest conviction.
3. **Correlation check** — correlated with existing positions? Would one event (a policy shift,
   a geopolitical headline) hit this *and* other holdings at once?
4. **Position sizing** — fits the speculative-sleeve allocation? Dollar risk = (entry − stop) ×
   size. Is that loss acceptable?
5. **News / catalyst scan** — upcoming catalysts (Fed, data, policy, geopolitics) that could
   override the technical setup?
6. **Round-number stop check** — is the stop sitting on a round number? Nudge it just past the
   psychological level (e.g., `$X.50`, not `$X.00`) to avoid stop-hunts.

---

## Value Zones — Existing Positions

*Add levels for names already held.*

| Ticker | Avg Cost | Value Zone(s) | Notes |
|--------|----------|---------------|-------|
| `{{TICKER}}` | `{{AVG_COST}}` | `{{ADD_LEVELS}}` | `{{NOTES}}` |

---

## Tactical Dry-Powder Framework

*Pre-committed deployment plans — written during clear thinking, executed during chaos.*

**Cash on hand:** `{{CASH_AMOUNT}}`
- **Primary uses:** `{{PRIMARY_USES}}` *(which entries / adds this cash is earmarked for)*
- **Reserved for opportunistic buys:** `{{RESERVE}}`
- **Discipline rule:** `{{DISCIPLINE_RULE}}` *(e.g., "deploy on technical confirmation or hit
  zones, not on headlines/FOMO")*

**Drawdown triggers** *(optional)* — pre-defined "if the market drops X%, I do Y":
- `{{DRAWDOWN_TRIGGER}}` *(e.g., "S&P −10–15% → shift managed account toward equities")*

---

## Earnings / Events Calendar

*Forward-looking. Prune elapsed rows.*

| Date | Event | Impact Area | Notes |
|------|-------|-------------|-------|
| `{{DATE}}` | `{{EVENT}}` | `{{AREA}}` | `{{NOTES}}` |

---

## Themes NOT Pursuing (and why)

*Saying no on purpose is a position. Record the reasoning so it isn't relitigated every week.*

| Theme | Reason |
|-------|--------|
| `{{THEME}}` | `{{REASON}}` |

---

## Removed from Watch

| Ticker | Date | Reason | Lesson |
|--------|------|--------|--------|
| `{{TICKER}}` | `{{DATE}}` | `{{REASON}}` | `{{LESSON}}` |

---

*To update: add names, entry targets, and technical levels as they develop.*
