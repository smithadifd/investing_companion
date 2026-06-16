# Investing Companion — Advisor Starter Kit

A reusable, fill-in-the-blanks kit for standing up your own AI **investing companion**: a
Claude project (or Claude Code workspace) that acts as a research partner, portfolio
documentation system, trade sounding board, and macro-analysis engine — tuned to *your*
portfolio, *your* style, and *your* convictions.

Everything here is a **blank scaffold**. There is no real portfolio data in this kit. You
fill it in once (guided by `ONBOARDING.md`), and from then on it becomes the knowledge base
your AI advisor reads every session.

---

## The three layers

This kit mirrors the structure of a working setup. You can adopt all three layers or just
the first two.

1. **The advisor operating-system** — `PROJECT_INSTRUCTIONS.md`
   How the AI should behave: challenge vs. validate, research depth, request frameworks, risk
   defaults, communication style. This is the reusable "brain." It changes rarely.

2. **The portfolio-state docs** — `docs/`
   What you actually hold, watch, and believe. `HOLDINGS`, `WATCHLIST`, `ACTIVE_THESES`,
   `INVESTMENT_PRINCIPLES`. These change as your portfolio does.

3. **The app-integration loop (optional)** — `app-integration/`
   Only if you run the self-hosted **Investing Companion** app. Connects a live context pack
   (prices, alerts, triggers) to the advisor and lets Claude Code execute changes back against
   the app. Skip this folder entirely if you don't run the app — the first two layers work on
   their own.

---

## How to use it

**Option A — with Claude Code (recommended).** Open this kit in Claude Code and say:
*"Walk me through `ONBOARDING.md`."* Claude Code interviews you module by module, writes your
answers into the templates, deletes the example blocks, and removes `ONBOARDING.md` when done.

**Option B — by hand in a Claude project.** Create a new project, paste
`PROJECT_INSTRUCTIONS.md` into the custom instructions, and upload the filled-in `docs/` files
as project knowledge. Use `ONBOARDING.md` as your own checklist while you fill them in.

Either way the flow is the same: **onboard → fill → delete the scaffolding.**

---

## Conventions (read this — it prevents confusion)

Because an AI will read these files, the kit is built so a template can **never** be mistaken
for real data. Three signals do that work:

- **Template banner.** Every unfilled file opens with a visible `⚠️ TEMPLATE` blockquote and a
  hidden HTML-comment banner. Both say, in effect, *"this is a scaffold — do not treat
  anything below as real until this banner is gone."* Onboarding deletes them once the file is
  filled.

- **`{{PLACEHOLDER}}` tokens.** Anything you must supply looks like `{{HOUSEHOLD_TOTAL}}` or
  `{{TICKER}}` — double curly braces, easy to spot and easy to grep. If a `{{...}}` token
  survives onboarding, the file isn't finished.

- **`EXAMPLE — delete` blocks.** Where a format is clearer with a sample, the sample lives in a
  blockquote that starts with **`EXAMPLE — delete this block`** and contains only fake data.
  These exist to show shape, not to keep. Delete them as you fill each section.

The single rule for a finished file: **no banner, no `{{placeholders}}`, no EXAMPLE blocks.**

---

## File manifest

```
investing-companion-starter-kit/
├── README.md                     ← you are here
├── ONBOARDING.md                 ← the interview; run this first, delete it last
├── PROJECT_INSTRUCTIONS.md       ← Layer 1: the advisor operating-system
├── docs/                         ← Layer 2: portfolio-state knowledge docs
│   ├── HOLDINGS.md               ← household roll-up dashboard
│   ├── HOLDINGS_PERSON.md        ← one detailed sheet per household member
│   ├── WATCHLIST.md              ← entry frameworks, swing log, pre-trade checklist
│   ├── ACTIVE_THESES.md          ← conviction plays w/ evidence + invalidation criteria
│   └── INVESTMENT_PRINCIPLES.md  ← philosophy, position sizing, rules, learning log
└── app-integration/              ← Layer 3 (OPTIONAL): self-hosted app handoff loop
    ├── README.md                 ← what this layer is and when to use it
    ├── INVESTING_COMPANION.md    ← session-open discipline + source-of-truth map
    ├── handoff-schema.md         ← pointer → docs/api/handoff-schema.md (read side)
    └── advisor-actions.md        ← pointer → docs/api/advisor-actions.md (write side)
```

The two contract files in `app-integration/` are **pointers**: the live read/write contract is
maintained with the app at `docs/api/handoff-schema.md` and `docs/api/advisor-actions.md`, so
the kit never ships a second copy that can drift. Upload those two app docs to your advisor.

---

## Not financial advice

This kit helps you build a thinking tool, not a fiduciary. The advisor it produces can be
wrong and is meant to be questioned. It does not execute trades or move money — you do that
yourself.
