export const meta = {
  name: 'investing-companion-audit-sweep',
  description: 'Investing Companion-tuned full-codebase audit — wraps the toolkit audit-sweep with dual-stack (FastAPI backend + Next.js frontend) lens hints and writes audit state to the project memory dir',
  phases: [
    { title: 'Scan', detail: 'toolkit audit-sweep, Investing Companion-tuned' },
    { title: 'Write Plans', detail: 'one writer per lens' },
    { title: 'Track', detail: 'plans/README.md + memory/audit-state.md' },
  ],
}

// Thin wrapper over the shared toolkit auditor. The generic script is the single
// source of truth for the lens checklists and orchestration; this only injects
// Investing Companion-specific "where to look" hints (dual-stack: Python/FastAPI
// backend + Next.js/TS frontend) and the project's audit-state path.
// Override-able via args (e.g. args.lenses to restrict the run).
const A = args || {}

const HINTS = {
  security: `Dual-stack. BACKEND: backend/app/core/dependencies.py (require_not_demo gate — verify EVERY trade/watchlist/alert/event/settings/AI mutation depends on it, per AGENTS.md demo-mode contract), core/security is auth in services/auth.py + JWT via SECRET_KEY (core/config.py); core/rate_limit.py; backend/app/api/v1/endpoints/** (authz on every non-public route, request bodies validated by Pydantic schemas in backend/app/schemas/**). Per-user encrypted secrets (CLAUDE_API_KEY, SCHWAB_TOKEN) live in the user_settings model (db/models/user_settings.py) + services/settings.py — confirm they're never logged or echoed back in responses. Schwab OAuth flow in endpoints/schwab.py + services/data_providers/schwab.py. FRONTEND: frontend/src/lib/api/client.ts (token handling/storage), frontend/src/lib/contexts/** (auth context), frontend/src/app/settings/ (API-key entry surfaces).`,
  'testing-gaps': `~286 backend pytest fns already; gaps skew to newer service logic. BACKEND: prioritize services/ business logic edge cases — technical.py, entry_zones.py, trade_readiness.py, exposure.py, needs_attention.py, extended_movers.py, ratio.py, price_history.py — plus services/data_providers/{yahoo,schwab,finnhub}.py fallback/aggregation paths and tasks/{alerts,events,price_history,schwab}.py Celery logic. FRONTEND: vitest exists for some hooks (useAlert, useTrade); check frontend/src/lib/hooks/** for untested hooks (useAI, useDashboard, useEquity, useEvents, useExport) and frontend/src/components/** modals/pages. Prioritize scoring/analysis/provider-fallback edge cases over pure UI.`,
  maintainability: `BACKEND: keep endpoints thin — flag business logic leaking into backend/app/api/v1/endpoints/** that belongs in services/ (AGENTS.md layering: endpoints → services → models). Watch for oversized service modules (services/context_pack.py, services/technical.py). FRONTEND: business/data logic leaking into frontend/src/components/** or frontend/src/app/**/page.tsx that belongs in lib/hooks/ or lib/api/. Duplication across the two stacks (shared enums/constants re-declared in Python schemas vs frontend/src/lib/api/types.ts).`,
  performance: `BACKEND: async I/O correctness — no sync/blocking calls in async endpoints; SQLAlchemy 2.0 query patterns in services/** for N+1 and missing indexes (cross-check db/models/**); TimescaleDB hypertable queries in services/price_history.py (time-range filtering, aggregation). Provider fan-out in services/data_providers/ aggregator and Celery tasks/** (batching, rate-limit respect — Alpha Vantage 5 req/min). FRONTEND: TanStack Query cache config in frontend/src/lib/hooks/**, TradingView Lightweight Charts render paths in frontend/src/components/charts/**, useMemo + stable keys.`,
  dependencies: `Dual manifest. Read backend/requirements.txt AND frontend/package.json + frontend/package-lock.json only. Unused deps, major-version drift, runtime-vs-dev misplacement in each stack independently. Note the unofficial Yahoo provider dependency is fragile by design (AGENTS.md).`,
  'error-handling': `BACKEND: endpoints/** return consistent error shapes and correct HTTP codes; services/data_providers/** per-provider isolation + fallback (one failing provider must not break others — Yahoo/Schwab/Finnhub aggregator); timeouts on all external HTTP (Yahoo, Alpha Vantage, Schwab, Discord webhook in services/notifications/discord.py); Celery tasks/** per-item failure isolation + retry semantics. Schwab expired-token silent-fallback-to-Yahoo path (AGENTS.md gotcha) must be handled, not swallowed elsewhere. FRONTEND: frontend/src/lib/api/client.ts error normalization; TanStack Query error/loading states surfaced in components/pages.`,
  accessibility: `FRONTEND only. frontend/src/components/** (esp. ui/, charts/, alert/, trade/ modals) and frontend/src/app/**/page.tsx — accessible names, form labels, alt text, focus traps in Modal.tsx/ConfirmModal.tsx, keyboard nav, touch targets, color-contrast on PriceChange/StockCard status coloring.`,
  consistency: `BACKEND: Pydantic schema usage for all request/response (backend/app/schemas/**); SQLAlchemy 2.0 mapped_column style across db/models/**; service-layer pattern uniformity; ruff-clean. FRONTEND: no 'any' (strict TS); functional components + hooks; component files ComponentName.tsx, hooks useHookName.ts; TanStack Query for server state vs Zustand for client state (not mixed). Cross-stack: enum/status-string values agree between Python schemas and frontend/src/lib/api/types.ts.`,
  'correctness-bugs': `BACKEND: analysis/scoring logic in services/technical.py, entry_zones.py, trade_readiness.py, exposure.py, ratio.py (null/divide-by-zero, boundary conditions, currency/percent handling); services/alert.py + tasks/alerts.py alert evaluation (NOTE AGENTS.md known bug #48: percent_up/percent_down alerts ignore comparison_period; #49: forex symbols don't resolve in ratios — confirm status, don't re-report as new if unchanged); services/data_providers/ aggregator fallback ordering + dedup; Celery beat schedules in tasks/celery_app.py. AI advisor contract: services/context_pack.py (UNSUPPORTED_FEATURES authority) + schemas/context_pack.py (SCHEMA_VERSION / ADVISOR_ACTIONS_VERSION) + services/context_pack_outbox.py + services/handoff.py — version-stamp correctness. FRONTEND: frontend/src/lib/hooks/** state transitions, optimistic-update/rollback in mutation hooks.`,
  'docs-accuracy': `Verify AGENTS.md (repo map vs actual dirs, env-var table vs backend/app/core/config.py, demo-mode contract vs core/dependencies.py require_not_demo, provider table vs services/data_providers/, known-bugs list #48/#49 still accurate). Advisor contract docs are load-bearing: docs/api/handoff-schema.md (SCHEMA_VERSION) and docs/api/advisor-actions.md (ADVISOR_ACTIONS_VERSION) must match backend/app/schemas/context_pack.py; docs/api/API_SPECIFICATION.md vs endpoints/**. Flag undocumented endpoints/services and stale docs-site/ pages.`,
}

return await workflow(
  { scriptPath: '/Users/andrew/claude-toolkit/workflows/audit-sweep.js' },
  {
    repoRoot: '/Users/andrew/investing_companion',
    plansDir: '/Users/andrew/investing_companion/plans',
    auditStatePath: '/Users/andrew/.claude/projects/-Users-andrew-investing_companion/memory/audit-state.md',
    lensHints: HINTS,
    ...A,
  }
)
