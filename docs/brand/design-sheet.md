# Design sheet

How Investing Companion looks and behaves on screen. The mark is in `mark.svg` and its
README; this sheet covers everything else: surfaces, colour, type, components, charts and
layout. It is written from an approved mock-up of the four screens that matter most, and the
rules here are the ones that mock-up follows. When a page and this sheet disagree, the sheet
wins until it is changed.

## What the app is for on screen

Investing Companion is a pulse check first and an analysis tool second. The first screen you
see answers "what moved" without a tap: the market, your positions, the highlights from your
watchlists, in that order. Everything deeper (ratios, playbook, trades, technicals) is one tap
away and is where the density lives.

- The phone is the primary medium for the pulse check. Design the home, a watchlist and an
  equity page at 390 px first.
- The desktop is the wide version of the same system, not a different app. The deep-dive pages
  are ergonomic there: more columns, more rows, the same tokens and components.
- The register is a calm terminal: dense where the data is, quiet everywhere else. Nothing
  flashes, nothing animates to get attention.

## Surfaces

A dark room with one light in it. There is no light theme.

| Token | Value | Use |
|---|---|---|
| `base` | `#0a0a0a` | Page background (Tailwind `neutral-950`) |
| `raised` | `#171717` | Cards, panels, inputs, chips at rest (`neutral-900`) |
| `glass` | `rgba(10,10,10,0.78)` + `backdrop-filter: blur(20px)` | Phone tab bar, floating panels |
| `border-ghost` | `rgba(255,255,255,0.05)` to `0.08` | Card and row borders. Never a solid mid-grey line |
| `divider` | `rgba(255,255,255,0.05)` | Row separators inside a card |

Depth comes from the surface step (base to raised) and from the accent glow. The glow is the
only shadow: a soft, edgeless spread of the accent at 12 to 18 percent behind a primary button,
an active chip or a chart marker. No drop shadows with a visible edge, no bevels, no gradients
between two colours. The one gradient allowed is the fade under a chart line (see Charts).

## Colour

| Token | Value | Use |
|---|---|---|
| `accent` | `#2563eb` | The one light: primary buttons, active states, chart lines, the mark, focus rings |
| `accent-glow` | `rgba(37,99,235,0.12)` to `0.18` | Soft glow behind the accent: button shadow, active chip, hover |
| `accent-wash` | `rgba(37,99,235,0.14)` | Active chip and tab background |
| `text` | `#ffffff` | Primary text |
| `text-secondary` | `#adaaaa` | Labels, descriptions, secondary numbers, table headers (8.5:1 on base) |
| `text-muted` | `#767575` | Axis labels and non-essential captions only (4.3:1 on base, 3.9:1 on raised; never for text that must be read) |
| `gain` | `#22c55e` | Up, rise, good. Text and marks |
| `gain-wash` | `rgba(34,197,94,0.12)` | Background of a positive change chip |
| `loss` | `#ef4444` | Down, fall, bad. Text and marks |
| `loss-wash` | `rgba(239,68,68,0.12)` | Background of a negative change chip |
| `wait` | `#fbbf24` | Pending, stale, warning |

Rules:

- The accent is never small text. Blue-600 is 3.8:1 on base and lower on raised, below the
  floor for body text. Use it as fill (white text on it), as glow, as a line, as an active indicator. If blue
  words are ever needed, add a lighter text step and record it here.
- Gain and loss are data colours. They say which way a number went and nothing else. They never
  appear as decoration, in the brand, or on a chart line by default. Every gain or loss colour is
  paired with a glyph (▲ ▼) or a sign, so the meaning survives without colour.
- The chart line is the accent. The change figure and its chip carry the direction. This keeps
  the hero calm: one blue light, with the mood in the numbers beside it.
- One accent. No second coloured light anywhere on a screen.

## Type

Two text faces, one monospace for symbols, and a label voice. All Google-hosted, no font files.

| Role | Face | Notes |
|---|---|---|
| Body and headings | Inter | 400 body, 500 section titles, 600 headings and prices |
| Numbers | Inter with `font-variant-numeric: tabular-nums` | Every price, change, percentage and stat. Columns line up |
| Ticker symbols | JetBrains Mono 500 | Only symbols: `NET`, `AAPL`. The one monospace element, the terminal signature |
| Labels | Space Grotesk 500, uppercase, `letter-spacing: 0.2em` | Section labels, column headers, stat captions |

Scale (phone, desktop in brackets where different):

| Style | Size / line | Weight |
|---|---|---|
| Hero number | 34 px / 1 (32 px) | 600, tracking -0.02em |
| Equity price | 38 px / 1 | 600 |
| Page title | 24 px / 1.15 (20 px / 28 px) | 600 |
| Card title | 16 px / 24 px | 500 |
| Row primary (symbol, name) | 15 px (14 px) | 600 symbol, 400 name |
| Body | 14 px / 20 px | 400 |
| Secondary | 13 px | 400 |
| Caption | 12 px | 400 |
| Label | 11 px / 16 px (10 px in table headers) | 500, uppercase, tracked |
| Axis | 10 px | 400, `text-muted` (axis labels only) |

Numbers are formatted once, the same everywhere: thousands separators, two decimals for
prices, two decimals and a percent sign for changes, a leading glyph for direction. Large
figures abbreviate (`9.41M`, `96.3B`).

## Components

**Top bar (phone).** 56 px. Mark at 28 px plus the wordmark in Inter 600 15 px on the home;
back arrow, context, and one action on inner pages. Icon buttons are 40 px squares with a
20 px Lucide outline icon in `text-secondary`.

**Tab bar (phone).** 76 px including the home indicator. Five items: Home, Watchlists,
Market, Alerts, More. Glass surface, ghost top border. The active item's icon is in the accent
and its label in `text`; inactive items are `text-secondary`. Labels are 10 px.

**Navigation rail (desktop).** 220 px, collapses above the content on narrow windows. Items are
40 px rows, 14 px, `text-secondary`; the active item gets `accent-wash` and a 2 px accent bar on
its left edge.

**Chip.** 36 px tall (34 px on desktop), radius 8 px, `raised` with a ghost border. An active
chip is `accent-wash` with a 55 percent accent border and `accent-glow`. A chip that carries a
value shows the name in 12 px 500 and the value in 12 px 600 tabular, coloured gain or loss.
Chips are real buttons.

**Row (movers, watchlist).** 56 to 60 px on the phone, 48 px on the desktop. Left: symbol over
name, name truncates. Then a 64 by 24 px sparkline, the price right-aligned at 72 px, and a
change chip. Rows are links; the whole row is the target. Rows separate with `divider`.

**Change chip.** 74 by 28 px, radius 6 px, `gain-wash` or `loss-wash`, text 13 px 600 tabular in
`gain` or `loss`, with the direction glyph. On the desktop table the chip becomes plain
coloured text in its own column.

**Card.** `raised`, ghost border, radius 8 px, padding 16 px (20 px on the desktop). Cards do
not nest.

**Stat tile.** A card at 12 px padding with a 10 px caption in `text-secondary` and a 14 px 600
tabular value. Tiles sit in a three-column grid with 10 px gaps.

**Primary button.** 44 px tall, radius 8 px, `accent` fill, white 600 14 px text, `accent-glow`
as its shadow. One per view. **Secondary button:** the same size in `raised` with a ghost
border.

**Empty state.** A line of plain text in `text-secondary` inside a dashed ghost border, or a
small status disc with a sentence. It says what will appear there and when. Never an
illustration, never an exclamation mark.

**Range bar.** 6 px track in `raised`, the covered part in the accent at 35 percent, a 12 px
accent marker with a 2 px base ring and a soft glow.

## Charts

One line, one light. Charts follow the same physics as the rest of the screen.

- The line is 2 px, round joins and caps, in the accent. Under it, a fade from the accent at
  16 percent to transparent. Nothing else is filled.
- The reference line (previous close on a day chart, the period's first value otherwise) is a
  1 px dashed line in `#484847` at 60 percent, labelled at 10 px on the right. When the
  reference falls outside the series' range, the chart is scaled to the series and the reference
  is stated in a caption instead of stretching the plot.
- The last point gets an 8 px marker in the accent with a 2 px ring in the surface colour, and a
  20 px glow disc at 18 percent behind it.
- Axes are recessive: time labels only, 10 px `text-muted`, no vertical axis, no grid.
- Sparklines are 1.5 px lines in the accent with no fill, no marker and no axis, 64 by 24 px on
  the phone, 80 by 22 px on the desktop.
- Period selection is a row of chips: 1D, 1W, 1M, 1Y, with the active chip styled as above.
  Changing the period changes the change figure and its label ("today", "past week").
- Touch and hover: pressing and dragging on a chart shows a crosshair at the nearest point with
  the value and time in a small label, and the hero figure follows the finger until release. On
  the desktop the same happens on hover. This is the gesture that makes the pulse check feel
  finished; ship it with the first chart.
- Status colour on the line is a per-user setting, off by default. When on, the line and
  sparklines take `gain` or `loss` by the period's direction.

## Layout

**Phone (390 px).** Side gutter 20 px. Sections are separated by 24 to 28 px. Content scrolls
between a fixed top bar and the glass tab bar; the scroll area pads its bottom by the tab bar's
height. Horizontal chip rows bleed to the screen edge and scroll.

**Desktop (1280 px and up).** Navigation rail on the left, content padded 24 px top and 32 px
sides. The dashboard is two columns: the market card and the movers table at two parts, the
side column (needs attention, watchlists, sectors) at one part. Both columns wrap to a single
column under about 900 px. Wide tables scroll inside their card rather than the page.

**Home composition.** Market, positions, watchlist highlights, in that order. When the user has
positions, the portfolio value leads and the market line is the second block. When there are
none (a fresh install, the demo), the market leads. What a watchlist highlight is, and how the
portfolio block is sourced, is a product decision still open; the layout holds a slot for it.

**Desktop tables.** Column headers are labels (10 px, tracked, `text-secondary`). Rows are 48 px,
hover is `accent` at 6 percent. Numbers right-aligned and tabular.

## Motion

Almost none. Chip and tab changes are instant. Charts redraw without animation on period
change. The only motion is the crosshair following the finger.

## Accessibility

- Dark is the default and the only theme. Text is white or `text-secondary` on `base` or
  `raised`; both pass 4.5:1. `text-muted` is for axis labels and captions you can lose.
- Every direction colour comes with a glyph or sign. Nothing is colour alone.
- Touch targets are at least 40 px; rows and tab items are larger.
- Every control is a real button, link or input with a label. Icon-only buttons carry
  `aria-label`. Charts carry `role="img"` with a sentence that states the direction and size of
  the move.
- Focus rings are the accent at 2 px offset.

## Never

No light theme. No green or red as an accent or on the brand. No blue as small text. No
candlesticks on the pulse-check screens (they belong on the analysis chart with its controls).
No upward-arrow or rocket iconography. No gradient other than the chart fade. No drop shadows
with an edge. No emoji in the interface. No animated numbers. No second accent.

## The mock-up and what is still open

The approved mock-up shows the phone home, a watchlist, an equity page and the desktop home on
real demo data, with the tweaks (typeface, line colour) that were compared. It is the reference
for building; this sheet is the rule.

Still open, to be decided on a built page rather than here:

- The lighter blue text step, if blue words are ever needed.
- The exact crosshair label format on the phone.
- The portfolio block: its source and its shape, and what a watchlist highlight is.
