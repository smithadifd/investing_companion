# CLAUDE.md — Investing Companion

@AGENTS.md

Everything durable about this repo lives in the imported AGENTS.md — read it first.
Personal/operational config (deploy targets, the handoff-execution API reference, current
watchlist IDs) is in the gitignored CLAUDE.local.md — read it first if it exists;
CLAUDE.local.md.example shows its shape.

## Notes for Claude

- Backend layering is endpoints → services → models; put logic in `services/`, not endpoints.
- When a change touches what the app exports or the actions the advisor can drive, update the
  contract in the SAME PR (AGENTS.md § Conventions has the sync table). Not a follow-up.
- Verify a change before claiming it works: `ruff check backend/` + `pytest` for backend,
  `npm run type-check` + `npm run lint` + `npm test` for frontend.
- Don't run anything under `scripts/` (deploy/backup) or touch `docs/issues/017` as part of
  ordinary code work — those hit live hosts / track a deliberate blocked decision.

## End-of-session workflow

Public repo with branch protection — no direct push to main:

1. Feature branch → Conventional Commits.
2. `gh pr create`; wait for CI with `gh run watch <id> --exit-status`.
3. Squash-merge (`gh pr merge --squash --delete-branch`), switch to main + pull.
4. Deploy only when asked (`scripts/deploy-synology.sh`); apply pending migrations on prod.
5. Trim the CLAUDE.local.md session log; promote any durable lesson into AGENTS.md § gotchas.
