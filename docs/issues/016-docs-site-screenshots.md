# Issue 016: Add Screenshots to Docs Site Feature Pages

**Status:** Open
**Created:** 2026-04-23
**Priority:** Low
**Affects:** Docs site (`docs-site/`), feature pages

## Summary

The Astro Starlight docs site at `docs.smithadifd.com` ships without
screenshots. All seven feature pages read as text-only. A single
representative image at the top of each feature page would make the
docs scannable and give a visual anchor before the prose. This was
explicitly deferred during the P3 drafting pass so the site could land
and the deploy pipeline could be proven out first.

## Targets

Log into <https://invest.smithadifd.com> as `demo@example.com` /
`demo1234!`. The demo uses synthetic seed data and resets weekly, which
satisfies the plan's sensitive-data constraint.

Capture one image per feature page:

| Page | Shot |
| --- | --- |
| `docs-site/src/content/docs/features/equity-dashboard.md` | Equity detail view — chart + fundamentals tabs visible |
| `docs-site/src/content/docs/features/watchlists.md` | Watchlists index with at least two watchlists populated |
| `docs-site/src/content/docs/features/market-overview.md` | Sector heatmap + indices row |
| `docs-site/src/content/docs/features/ai-analysis.md` | AI panel on an equity page, mid-stream or with a completed response |
| `docs-site/src/content/docs/features/alerts.md` | Alerts management page with a mix of active and triggered alerts |
| `docs-site/src/content/docs/features/trade-tracker.md` | Trades table or the P&L dashboard with realized + unrealized numbers |
| `docs-site/src/content/docs/features/calendar.md` | Calendar month view with watchlist filter active |

## Implementation

1. Capture at 1280×720 or 1920×1080, cropped cleanly. Keep dark/light
   mode consistent across the set (match the existing brand).
2. Save under `docs-site/public/screenshots/` with descriptive names
   (e.g., `equity-dashboard.png`, `ai-analysis.png`).
3. Prefer lossless PNG, or WebP if file sizes run large.
4. Reference at the top of each feature page, below the frontmatter
   and above the first paragraph:

   ```markdown
   ![Equity dashboard](/screenshots/equity-dashboard.png)
   ```

5. Rebuild locally with `npm run build` from `docs-site/` to confirm
   the images resolve. Push to `main`; the `Docs site` workflow
   deploys to `docs.smithadifd.com`.

## Notes

- Screenshots should show synthetic seed data only. The demo already
  enforces this, but double-check no real personal watchlist or trades
  bleed in if capturing from a non-demo instance.
- Consider adding `loading="lazy"` via plain HTML `<img>` tags if
  page weight becomes an issue with all seven images loaded.
- The `docs-site/public/CNAME` file points to the custom domain; don't
  delete it when adding files under `public/`.
