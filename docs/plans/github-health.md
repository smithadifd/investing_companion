# Plan: GitHub Repository Health

## Overview

Set up CI, dependency monitoring, and branch protection to keep the repository healthy as it grows (and especially before any potential open-sourcing).

## Current State
- No `.github/` directory exists — no workflows, no dependabot, no templates
- `test-build.sh` exists locally (TypeScript + ESLint + ruff + Docker build)
- Backend pytest infrastructure was just set up (tests exist and pass)
- No branch protection rules

---

## 1. GitHub Actions CI Workflow

**File**: `.github/workflows/ci.yml`

Trigger on push to `main`/`develop` and all PRs.

**Jobs:**

### Backend
- Install Python 3.11, install requirements
- `ruff check backend/`
- `cd backend && python -m pytest tests/ -v --cov=app`
- Optionally: `mypy backend/app/`

### Frontend
- Install Node 20, `npm ci`
- `npm run type-check`
- `npm run lint`
- (Future: `npm test` once frontend tests exist)

### Docker Build
- Build images with `docker compose -f docker-compose.local.yml build`
- Validates that everything compiles into working images

**Notes:**
- Needs a PostgreSQL service container for backend tests (or mock-only tests)
- Redis service container for any integration tests
- Use `pytest.ini` config that's already set up

---

## 2. Dependabot Configuration

**File**: `.github/dependabot.yml`

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/backend"
    schedule:
      interval: "weekly"
    reviewers:
      - "drew4bucks"  # or GitHub username
    open-pull-requests-limit: 5

  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
    reviewers:
      - "drew4bucks"
    open-pull-requests-limit: 5

  - package-ecosystem: "docker"
    directory: "/docker"
    schedule:
      interval: "monthly"
```

Covers Python deps, npm deps, and Docker base images.

---

## 3. Branch Protection

Configure via GitHub settings (or `gh api`):

**`main` branch:**
- Require PR reviews (1 reviewer — can be yourself)
- Require CI status checks to pass before merging
- No force pushes
- No direct pushes (all changes via PR)

**`develop` branch:**
- Require CI status checks to pass
- Allow direct pushes (for solo dev speed)

---

## 4. Issue & PR Templates (optional)

**File**: `.github/ISSUE_TEMPLATE/bug_report.md`
**File**: `.github/ISSUE_TEMPLATE/feature_request.md`
**File**: `.github/PULL_REQUEST_TEMPLATE.md`

Keep these minimal — you're the primary developer. Light templates that match your existing issue format in `docs/issues/`.

---

## Estimated Scope
- CI workflow: ~80 lines
- Dependabot config: ~25 lines
- PR/issue templates: ~40 lines
- Branch protection: manual config or `gh` CLI commands
- **Total**: ~145 lines, 4-5 files
