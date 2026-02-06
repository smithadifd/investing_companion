# Issue 014: Intelligent Product Agents

**Status**: Planned
**Priority**: Medium
**Affects**: Notifications, AI, Trading, Alerts

## Overview

Add autonomous AI-powered agents that enhance the app's intelligence layer — moving it from purely informational to actionable and proactive.

## Proposed Agents

### Tier 1: High Value

1. **News & Catalyst Aggregator** — Pull news/catalysts for watchlist items, inject context into morning pulse and EOD wrap. "UUUU up 5%" becomes "UUUU up 5% — DOE announced new uranium reserve program."

2. **Trade Journal & Pattern Analysis** — Analyze closed trades for behavioral patterns (e.g., "you sold winners 3x faster than losers"), score entry/exit quality, generate weekly review summaries via Discord.

3. **Daily Strategy Agent** — Morning game plan with actionable context: "SPY near resistance, UUUU earnings tonight — your position is exposed, CCJ testing 200 MA where it's bounced 3x." Transforms morning pulse from informational to strategic.

### Tier 2: Builds on Tier 1

4. **Technical Pattern Recognition** — Auto-detect breakouts, volume anomalies, support/resistance tests on watchlist items. Auto-create alerts when patterns form.

5. **Pre-Market Screening** — 9:25 AM task scanning watchlist for gap-ups/downs, earnings surprises, unusual pre-market volume.

6. **Macro Event Impact Analyzer** — Historical impact analysis for calendar events ("last 5 CPIs averaged +0.8% SPY move, you have 40% rate-sensitive exposure").

### Tier 3: Nice to Have

7. **Data Validation Agent** — Health checks on Yahoo Finance, stale cache detection, anomaly flagging.

8. **Position Sizing Optimizer** — Kelly Criterion, volatility-adjusted sizing, sector concentration warnings.

## Prerequisites

- Issue #001 (Claude OAuth/API) must be resolved for AI-powered agents (3, 6, 8)
- News data provider needed for agent 1 (Alpha Vantage news, Finnhub, or similar)

## Implementation Notes

- All agents should be toggleable via Settings UI
- Actions are advisory only — never auto-execute trades
- New DB tables likely needed: `news_items`, `trade_journal_entries`, `strategy_signals`
- New Celery tasks for scheduling agent runs
- Leverage existing notification formatters for Discord output

## Related Issues

- #001 (Claude OAuth — blocks AI agents)
- #007 (News integration — overlaps with Agent 1)
- #013 (News page — overlaps with Agent 1)
