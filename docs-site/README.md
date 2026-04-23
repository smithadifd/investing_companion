# Investing Companion docs site

Documentation site for the Investing Companion project. Built with
[Astro Starlight](https://starlight.astro.build/) and deployed to GitHub
Pages at [docs.smithadifd.com](https://docs.smithadifd.com).

## Layout

```
src/
  content/
    docs/
      index.md                  Home
      architecture/             Overview, data flow, domain model
      features/                 One page per user-facing feature
      running/                  Quick start, config, deployment, backup, security
      design-decisions/         Why the stack looks the way it does
      roadmap.md
      contributing.md
public/
  CNAME                         Custom domain for GitHub Pages
astro.config.mjs                Site config, sidebar, integrations
```

## Local development

```bash
nvm use            # pin Node 22
npm ci
npm run dev        # http://localhost:4321
```

## Build

```bash
npm run build      # writes static site to ./dist
npm run preview    # serves the build on a local port
```

## Deploy

Pushes to `main` that touch `docs-site/**` run the
[`docs-site`](../.github/workflows/docs-site.yml) workflow, which builds
and publishes to GitHub Pages. No action required beyond merging.

## Content conventions

- Pages live in `src/content/docs/` and are routed by filename.
- Sidebar order is defined explicitly in `astro.config.mjs` — new pages
  must be registered there to appear in navigation.
- Sentence-case headings. No emoji. No marketing voice.
- Cross-link to code in the main repo with full paths
  (`backend/app/services/equity.py`), not relative paths, so links remain
  valid when the docs are viewed on the deployed site.
- Do not include real trade data, API keys, or personal auth credentials.
  Use placeholder values (`your-secret-key-here`).

## Related

- Plan: [`docs/plans/doc-site-plan.md`](../docs/plans/doc-site-plan.md)
  in the main repo — source of truth for scope, audience, and content
  inventory.
