# Issue 002: Add Local Production Build Testing

**Status:** Open
**Created:** 2026-02-01
**Priority:** Low
**Affects:** Deployment workflow

## Summary

During the Phase 6.6 Synology deployment, several build errors were discovered that could have been caught earlier with local Docker build testing before deploying.

## Issues Discovered During Deployment

- TypeScript errors (Set iteration, missing imports, Lucide icon prop)
- Missing `public` folder for Next.js standalone build
- npm ci needing devDependencies for build stage
- NEXT_PUBLIC_API_URL not being baked into the build

## What Local Testing Would NOT Have Caught

- `service_completed_successfully` docker-compose v1 incompatibility (Mac has v2)
- Runtime import collision (`settings` vs `app_settings`) - only manifests at runtime

## Proposed Solution

Add a pre-deployment step to run the production Docker build locally:

```bash
docker compose -f docker-compose.local.yml build
```

## Acceptance Criteria

- [ ] Document local build testing in DEPLOYMENT.md
- [ ] Consider adding a `scripts/test-build.sh` script
- [ ] Add to pre-deployment checklist

## Related

- Commit `0d21958` - fix: resolve deployment issues for Synology production build
