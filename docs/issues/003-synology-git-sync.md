# Issue 003: Synology Git Repository Sync

**Status:** Open
**Created:** 2026-02-01
**Priority:** Medium
**Affects:** Deployment workflow, updates

## Summary

Git on Synology NAS fails to clone repositories via SMB-mounted filesystem. The repository was manually copied from Mac, and subsequent updates require re-syncing.

## Current State

| Location | Commit | Status |
|----------|--------|--------|
| Mac | `0d21958` | Current |
| GitHub | `0d21958` | Current |
| Synology | `056948e` | One commit behind (files manually updated) |

The Synology has the correct working files, but git thinks it's on the older commit.

## Data Safety

**User data is safe.** Data lives in Docker volumes, separate from code:
- `investing_postgres_data` - Database
- `investing_redis_data` - Cache

Code updates via `git pull` will not affect these volumes.

## Resolution Steps

When git is working on Synology:

```bash
cd /volume1/docker/investing_companion

# Check what git sees as changed
git status

# Stash local changes (safety)
git stash

# Pull latest from GitHub
git pull origin main

# Files should match - drop stash
git stash drop

# Rebuild containers
docker compose -f docker-compose.local.yml up -d --build
```

## Backup Before First Pull

Run backup script before first git pull (just in case):

```bash
./scripts/backup.sh
```

## Root Cause Investigation

- SMB filesystem may have permission/symlink issues with git
- SSH directly into Synology might work better than SMB mount
- Consider using Git Package from Synology Package Center

## Related

- Phase 6.6 deployment
