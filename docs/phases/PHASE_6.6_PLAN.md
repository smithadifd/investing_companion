# Phase 6.6: Deployment Readiness & Polish

**Goal**: Prepare the application for production deployment on Synology NAS with security hardening, code cleanup, and essential missing features.

**Status**: PLANNED (after Phase 6.5 Calendar & Events)

---

## Overview

Phase 6.6 bridges the gap between feature-complete MVP (Phase 6.5) and production deployment. This phase focuses on:
1. Security hardening
2. Code quality improvements (DRY, consistency)
3. Deployment preparation for Synology
4. Database seeding for production
5. Missing MVP features

---

## 1. Security Hardening

### 1.1 Critical: Credential Rotation
- [ ] Rotate Discord webhook URL (exposed in conversation)
- [ ] Rotate Claude API key (exposed in conversation)
- [ ] Document credential rotation process

### 1.2 Configuration Security
- [ ] Remove default secrets from code (fail loudly if not configured)
- [ ] Add `.env.example` with documented placeholders
- [ ] Validate required environment variables on startup
- [ ] Add production configuration validation

### 1.3 Authentication Improvements
- [ ] Add login rate limiting (5 attempts per 15 minutes)
- [ ] Add session cleanup scheduled task (remove expired sessions)
- [ ] Enforce strong password requirements in frontend/backend

### 1.4 Security Headers
- [ ] Add security middleware (X-Frame-Options, X-Content-Type-Options, etc.)
- [ ] Configure CORS properly for production domain
- [ ] Add CSP headers to frontend

### 1.5 Database Security
- [ ] Add CHECK constraints for positive trade quantities/prices
- [ ] Remove nullable user_id from alerts (enforce ownership)
- [ ] Add database-level constraints for data integrity

---

## 2. Code Quality & Consistency

### 2.1 Backend DRY Improvements
- [ ] Create shared response utilities (standardize meta creation)
- [ ] Create base service class for common CRUD patterns
- [ ] Standardize error response format across all endpoints
- [ ] Add proper logging throughout services (structured logging)

### 2.2 Frontend DRY Improvements
- [ ] Audit component patterns for consistency
- [ ] Standardize error handling in API calls
- [ ] Create shared form validation utilities

### 2.3 Resource Management
- [ ] Fix ThreadPoolExecutor leak in Yahoo provider (add shutdown)
- [ ] Add request timeouts to external API calls
- [ ] Implement graceful shutdown for Celery workers

### 2.4 Error Handling
- [ ] Replace generic `except Exception` with specific exceptions
- [ ] Add proper error logging with context
- [ ] Ensure external API errors don't leak sensitive data

---

## 3. Synology Deployment Preparation

### 3.1 Docker Compose Production
- [ ] Create `docker-compose.prod.yml` for production
- [ ] Remove volume mounts for source code (use built images)
- [ ] Add init container for database migrations
- [ ] Configure proper resource limits
- [ ] Add healthchecks for all services

### 3.2 Environment Configuration
- [ ] Create `.env.production.example` with all production variables
- [ ] Document required vs optional environment variables
- [ ] Add environment validation script
- [ ] Audit all DATABASE_URL references (fix "investing" vs actual DB name mismatch)

### 3.3 Reverse Proxy Setup
- [ ] Add Traefik configuration for HTTPS
- [ ] Configure Let's Encrypt certificate automation
- [ ] Add rate limiting at proxy level
- [ ] Document Synology-specific setup steps

### 3.4 Backup Strategy
- [ ] Add pg_dump backup script
- [ ] Create cron job for automated backups
- [ ] Document restore procedure

### 3.5 Monitoring & Logging
- [ ] Add comprehensive health endpoint (checks DB, Redis, external APIs)
- [ ] Document Uptime Kuma integration
- [ ] Add basic request logging for debugging
- [ ] Review application logs for errors/warnings
- [ ] Fix stray database connection attempt to "investing" (should be actual DB name)
- [ ] Configure log rotation for production
- [ ] Set appropriate log levels (INFO in prod, DEBUG in dev)

---

## 4. Database Seeding

### 4.1 Production Seed Data
Create seed script with:

#### Default Ratios
| Ratio | Numerator | Denominator | Category | Description |
|-------|-----------|-------------|----------|-------------|
| Gold/Silver | GLD | SLV | Commodity | Historical average ~60, extremes signal rotation |
| SPY/QQQ | SPY | QQQ | Equity | Tech vs broad market sentiment |
| Value/Growth | VTV | VUG | Equity | Factor rotation indicator |
| TLT/IEF | TLT | IEF | Macro | Yield curve slope proxy |
| Copper/Gold | CPER | GLD | Macro | Economic growth expectations |
| URA/XLE | URA | XLE | Equity | Uranium vs traditional energy |

#### Market Indices
| Symbol | Name | Region | Display Order |
|--------|------|--------|---------------|
| ^GSPC | S&P 500 | US | 1 |
| ^DJI | Dow Jones | US | 2 |
| ^IXIC | NASDAQ | US | 3 |
| ^RUT | Russell 2000 | US | 4 |
| ^VIX | VIX | US | 5 |
| ^TNX | 10-Year Treasury | US | 6 |

#### Sample Watchlist (Optional)
- "Core Holdings" watchlist with typical long-term positions
- "Watchlist" default watchlist

### 4.2 Seed Script Features
- [ ] Idempotent (can run multiple times safely)
- [ ] Configurable via environment variable
- [ ] Skip if data exists
- [ ] Log what was seeded

---

## 5. Missing MVP Features

### 5.1 Enhanced Health Endpoint
- [ ] Check database connectivity
- [ ] Check Redis connectivity
- [ ] Check external API status (non-blocking)
- [ ] Return version info
- [ ] Return uptime

### 5.2 API Documentation
- [ ] Enable OpenAPI/Swagger UI in production
- [ ] Add descriptions to all endpoints
- [ ] Document request/response examples

### 5.3 Data Validation Improvements
- [ ] Validate equity symbols before API calls
- [ ] Add pagination to all list endpoints
- [ ] Add proper input length limits

### 5.4 User Experience
- [ ] Add "forgot password" flow (email or recovery codes)
- [ ] Add loading states for slow operations
- [ ] Add error boundary in frontend

---

## 6. Documentation Updates

### 6.1 Update Existing Docs
- [ ] Update ROADMAP.md with Phase 6.5
- [ ] Update CLAUDE.md with deployment commands
- [ ] Create/update architecture diagrams

### 6.2 New Documentation
- [ ] Create DEPLOYMENT.md (Synology-specific guide)
- [ ] Create BACKUP.md (backup/restore procedures)
- [ ] Create SECURITY.md (security practices)
- [ ] Create TROUBLESHOOTING.md

---

## Implementation Order

### Week 1: Security & Critical Fixes
1. Credential rotation (manual - document process)
2. Configuration security (remove defaults, add validation)
3. Security headers and CORS
4. Database constraints
5. Resource management fixes

### Week 2: Deployment Prep
1. Production docker-compose
2. Traefik/HTTPS setup
3. Database migrations automation
4. Seed script
5. Health endpoint enhancements

### Week 3: Polish & Documentation
1. Code DRY improvements
2. Error handling standardization
3. All documentation
4. Final testing

---

## Success Criteria

- [ ] Application starts with production configuration
- [ ] No hardcoded secrets or weak defaults
- [ ] All sensitive endpoints rate-limited
- [ ] Database seeded with useful starting data
- [ ] Automated HTTPS with Let's Encrypt
- [ ] Automated database backups
- [ ] Health endpoint reports accurate system status
- [ ] Documentation sufficient for fresh deployment

---

## Files to Create/Modify

### New Files
- `docker-compose.prod.yml`
- `docker/traefik/traefik.yml`
- `docker/traefik/dynamic.yml`
- `backend/scripts/seed_demo_data.py`
- `scripts/backup.sh`
- `scripts/restore.sh`
- `.env.production.example`
- `docs/DEPLOYMENT.md`
- `docs/BACKUP.md`
- `docs/SECURITY.md`

### Modified Files
- `backend/app/core/config.py` - Add validation
- `backend/app/main.py` - Add security middleware
- `backend/app/api/v1/endpoints/health.py` - Enhanced checks
- `backend/app/services/data_providers/yahoo.py` - Fix resource leak
- `docker-compose.yml` - Add migration init
- `CLAUDE.md` - Update with deployment info
- `docs/ROADMAP.md` - Add Phase 6.5

---

## Notes

- Phase 6.5 is focused on deployment readiness, not new features
- Security is the top priority
- Keep changes minimal and focused
- Test thoroughly before deploying to Synology
