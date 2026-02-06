# Plan: Upgrade Next.js 14 → 16 + ESLint 9

## Motivation

- **Security**: Next.js 10.0–15.5.x has 2 high-severity vulnerabilities (DoS via Image Optimizer, HTTP deserialization DoS with RSC). Fixed in 16.x.
- **Maintenance**: ESLint 8 is EOL. eslint-config-next ships with a vulnerable `glob` dependency. Upgrading Next.js 16 removes `next lint` entirely, requiring ESLint 9 flat config.
- **Evergreen**: Node 22 LTS + React 19 + Next.js 16 puts us on current stable for everything.

## Current State

| Dependency | Current | Target |
|---|---|---|
| next | ^14.2.29 | ^16.x |
| react / react-dom | ^18.2.0 | ^19.x |
| @types/react / @types/react-dom | ^18.x | ^19.x |
| eslint | ^8.56.0 | ^9.x |
| eslint-config-next | ^14.2.29 | ^16.x |
| Node Docker image | 22-alpine | 22-alpine (no change) |

## Risk Assessment: LOW

The codebase is well-positioned for this upgrade:
- **All pages are client components** (`'use client'`) — no server-side `params`/`searchParams` async migration needed
- **Dynamic routes use `useParams()` hook** (client-side), not server-side `params` props
- **No `next/image`** usage (images.unoptimized: true)
- **No API routes**, no middleware, no Suspense, no `cookies()`/`headers()`
- **No custom Webpack config** — Turbopack transition is seamless
- **No parallel routes** — no `default.js` requirement
- **TanStack Query handles caching** — unaffected by Next.js caching default changes
- **Simple ESLint config** — single-line `.eslintrc.json`

## Steps

### 1. Upgrade React 18 → 19

```bash
npm install react@latest react-dom@latest @types/react@latest @types/react-dom@latest
```

**Check third-party compatibility:**
- `@tanstack/react-query` v5 — supports React 19 ✅
- `zustand` v4 — supports React 19 ✅
- `next-themes` v0.4 — supports React 19 ✅
- `lucide-react` v0.563 — supports React 19 ✅
- `@testing-library/react` v16 — supports React 19 ✅

**React 19 breaking changes to watch for:**
- `forwardRef` no longer needed (but still works, no rush to remove)
- Stricter hydration error reporting (we're all client components, low risk)
- `useFormState` renamed to `useActionState` (we don't use either)

### 2. Upgrade Next.js 14 → 16

```bash
npm install next@latest eslint-config-next@latest
```

**What changes:**
- Turbopack becomes default bundler (no custom Webpack = seamless)
- `next lint` command removed — must use ESLint CLI directly
- Caching defaults changed (no impact — TanStack Query handles our caching)
- `output: 'standalone'` still supported ✅

**Verify:**
- `npm run build` succeeds
- `npm run dev` works (Turbopack)
- Dynamic routes `/equity/[symbol]` and `/watchlists/[id]` work
- All `next/link` navigation works
- Docker standalone build still works

### 3. Migrate ESLint 8 → 9 (flat config)

**Delete** `.eslintrc.json`

**Create** `eslint.config.mjs`:
```js
import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({ baseDirectory: __dirname });

const eslintConfig = [
  ...compat.extends("next/core-web-vitals"),
];

export default eslintConfig;
```

> Note: Check if eslint-config-next 16.x ships native flat config support.
> If so, use the simpler format:
> ```js
> import nextVitals from 'eslint-config-next/core-web-vitals';
> export default [nextVitals];
> ```

**Update** `package.json` scripts:
```json
"lint": "eslint src/",
"lint:fix": "eslint src/ --fix"
```

**Install** ESLint 9:
```bash
npm install eslint@latest --save-dev
```

### 4. Update package.json version ranges

Ensure `package.json` pins are updated:
```json
"next": "^16.0.0",
"react": "^19.0.0",
"react-dom": "^19.0.0",
"eslint": "^9.0.0",
"eslint-config-next": "^16.0.0",
"@types/react": "^19.0.0",
"@types/react-dom": "^19.0.0"
```

### 5. Run tests and verify

- `npm test` — all 61 frontend tests pass
- `npm run build` — production build succeeds
- `npm run lint` — ESLint 9 works with new config
- `npm run type-check` — TypeScript happy
- Docker build test: `docker build -f docker/Dockerfile.frontend.prod .`

### 6. Update dependabot ignore rules

After upgrade, update `.github/dependabot.yml` to remove the ESLint 9 ignore rule (since we'll be on 9.x).

## Out of Scope

- **Tailwind CSS 3 → 4** — separate effort, no security impact, lower priority
- **Converting client components to server components** — not needed, working fine as-is
- **Removing `forwardRef`** — still works in React 19, can clean up opportunistically later

## Rollback

If issues arise, revert the commit and `npm ci` to restore the lockfile. The Docker images pin `npm ci` against the lockfile, so deployment is deterministic.
