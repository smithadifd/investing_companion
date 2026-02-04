# Deployment Improvements Plan

**Created:** 2026-02-04
**Status:** Planning
**Priority:** High - Foundational for future development

---

## Executive Summary

Two main areas need improvement based on Phase 6.6 deployment pain:

1. **Git on Synology** - Currently broken; can't pull updates
2. **CI/CD Pipeline** - No pre-deployment testing; manual rebuild process

---

## Part 1: Fix Git on Synology

### Current Problem

| Issue | Impact |
|-------|--------|
| Git clone fails over SMB | Can't use git commands from Mac |
| Commit mismatch | Synology at `056948e`, GitHub at `0d21958` |
| Manual file copy | Error-prone, no version tracking |

### Proposed Solution: SSH + Native Git

Instead of using git over SMB (which has permission/symlink issues), work directly on the Synology via SSH.

#### Step 1: Enable SSH on Synology

1. DSM Control Panel → Terminal & SNMP
2. Enable SSH service
3. Set port (default 22 or custom for security)

#### Step 2: Install Git Package

Option A - Synology Package Center:
- Install "Git Server" package (provides git CLI)

Option B - Entware/opkg (if Package Center version is old):
```bash
# If Entware is installed
opkg install git
```

#### Step 3: Configure Git SSH Access to GitHub

```bash
# SSH into Synology
ssh admin@your-nas-ip

# Generate SSH key (if not exists)
ssh-keygen -t ed25519 -C "synology-nas"

# Display public key
cat ~/.ssh/id_ed25519.pub

# Add this key to GitHub: Settings → SSH Keys
```

#### Step 4: Fix Current Repository State

```bash
cd /volume1/docker/investing_companion

# Backup first
./scripts/backup.sh /volume1/backups/investing

# Check current state
git status
git log --oneline -5

# Option A: If git sees changes, reset to match remote
git fetch origin main
git reset --hard origin/main

# Option B: If git is totally confused, re-clone
cd /volume1/docker
mv investing_companion investing_companion.bak
git clone git@github.com:YOUR_USERNAME/investing_companion.git
# Copy back .env.production
cp investing_companion.bak/.env.production investing_companion/
```

#### Step 5: Test Pull Workflow

```bash
# From Mac, make a small change, commit, push
# Then on Synology:
cd /volume1/docker/investing_companion
git pull origin main

# Rebuild if changes affect code
docker-compose -f docker-compose.local.yml up -d --build
```

### Deliverables

- [ ] SSH enabled on Synology
- [ ] Git installed and working natively
- [ ] SSH key added to GitHub
- [ ] Repository sync verified
- [ ] Document workflow in DEPLOYMENT.md

---

## Part 2: CI/CD Improvements

### Current Pain Points

| Problem | Impact |
|---------|--------|
| No local build testing | Errors found during Synology deploy |
| Manual rebuild process | SSH → cd → git pull → docker-compose |
| No automated tests before deploy | TypeScript errors slip through |
| Docker Compose v1 vs v2 differences | Some features don't work on Synology |

### Proposed Solution: Multi-Layer CI/CD

```
┌─────────────────────────────────────────────────────────────┐
│  LOCAL DEVELOPMENT (Mac)                                    │
│  ─────────────────────                                      │
│  • npm run dev / uvicorn --reload                          │
│  • Fast iteration                                           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  PRE-COMMIT / PRE-PUSH HOOKS                               │
│  ────────────────────────────                              │
│  • TypeScript check (tsc --noEmit)                         │
│  • Python linting (ruff)                                   │
│  • Quick unit tests                                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  LOCAL BUILD TEST (scripts/test-build.sh)                  │
│  ─────────────────────────────────────────                 │
│  • Build production Docker images locally                  │
│  • Catches 90% of deployment errors before push            │
│  • Run manually before deploying                           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  GITHUB ACTIONS (optional, future)                         │
│  ─────────────────────────────────                         │
│  • Run tests on push                                       │
│  • Build Docker images                                     │
│  • Could push to Docker Hub for Synology pull              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  SYNOLOGY DEPLOYMENT                                       │
│  ────────────────────                                      │
│  • git pull origin main                                    │
│  • docker-compose up -d --build                            │
│  • OR: docker-compose pull && up (if using Docker Hub)     │
└─────────────────────────────────────────────────────────────┘
```

### Implementation Phases

#### Phase A: Local Build Testing Script (Quick Win)

Create `scripts/test-build.sh`:

```bash
#!/bin/bash
set -e

echo "=== Testing Production Build ==="

# Frontend type check
echo "→ TypeScript check..."
cd frontend && npm run type-check && cd ..

# Backend lint
echo "→ Python lint..."
cd backend && ruff check . && cd ..

# Build Docker images (without running)
echo "→ Building Docker images..."
docker compose -f docker-compose.local.yml build

echo "✓ Build test passed!"
```

**Deliverables:**
- [ ] Create `scripts/test-build.sh`
- [ ] Add `type-check` script to frontend package.json
- [ ] Document in DEPLOYMENT.md pre-deploy checklist

#### Phase B: Git Hooks (Recommended)

Add pre-push hook to catch issues before GitHub:

`.git/hooks/pre-push`:
```bash
#!/bin/bash
echo "Running pre-push checks..."

# TypeScript
cd frontend && npm run type-check || exit 1

# Python
cd ../backend && ruff check . || exit 1

echo "Pre-push checks passed!"
```

**Deliverables:**
- [ ] Create hook scripts
- [ ] Add setup script to install hooks
- [ ] Document in CONTRIBUTING.md or CLAUDE.md

#### Phase C: Simplified Synology Deploy Script

Create `scripts/deploy-synology.sh` (run FROM Mac):

```bash
#!/bin/bash
set -e

SYNOLOGY_HOST="admin@your-nas-ip"
DEPLOY_PATH="/volume1/docker/investing_companion"

echo "=== Deploying to Synology ==="

# 1. Run local build test first
./scripts/test-build.sh

# 2. Push to GitHub
git push origin main

# 3. SSH to Synology and deploy
ssh $SYNOLOGY_HOST << 'ENDSSH'
cd /volume1/docker/investing_companion
git pull origin main
docker-compose -f docker-compose.local.yml up -d --build
docker-compose ps
ENDSSH

echo "✓ Deployment complete!"
echo "→ Check http://your-nas-ip:3000"
```

**Deliverables:**
- [ ] Create `scripts/deploy-synology.sh`
- [ ] Test end-to-end workflow
- [ ] Add to DEPLOYMENT.md

#### Phase D: GitHub Actions (Future/Optional)

For when you want automated CI:

`.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Frontend checks
        run: |
          cd frontend
          npm ci
          npm run type-check
          npm run lint

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Backend checks
        run: |
          cd backend
          pip install ruff
          ruff check .

      - name: Build Docker images
        run: |
          docker compose -f docker-compose.local.yml build
```

**Deliverables:**
- [ ] Create `.github/workflows/ci.yml`
- [ ] Test workflow
- [ ] Add status badge to README

---

## Implementation Priority

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| **1** | Fix Git on Synology (Part 1) | 30 min | Critical - enables all updates |
| **2** | Create test-build.sh (Phase A) | 15 min | High - catches build errors |
| **3** | Create deploy-synology.sh (Phase C) | 15 min | High - one-command deploy |
| **4** | Git hooks (Phase B) | 20 min | Medium - automated safety |
| **5** | GitHub Actions (Phase D) | 30 min | Low - nice to have |

---

## Success Criteria

After implementation:

1. **Git works on Synology**
   - Can `git pull` from Synology SSH
   - Commit hashes match across Mac/GitHub/Synology

2. **Build errors caught locally**
   - `./scripts/test-build.sh` catches TypeScript/Python issues
   - No more surprise errors during Synology deployment

3. **One-command deployment**
   - `./scripts/deploy-synology.sh` handles full workflow
   - Push → Pull → Build → Verify in single command

4. **Documented workflow**
   - DEPLOYMENT.md updated with new procedures
   - Clear pre-deployment checklist

---

## Notes

- Synology uses Docker Compose v1 - avoid v2-only features
- Keep backup before first git sync: `./scripts/backup.sh`
- User data safe in Docker volumes (separate from code)

---

## Related Issues

- [002-local-build-testing.md](../issues/002-local-build-testing.md)
- [003-synology-git-sync.md](../issues/003-synology-git-sync.md)
