#!/bin/bash
# Deploy to Synology NAS
# Runs build tests, pushes to GitHub, then pulls and rebuilds on Synology

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Configuration
SYNOLOGY_HOST="synology"
DEPLOY_PATH="/volume3/docker/investing_companion"
GIT_PATH="/usr/local/bin/git"
DOCKER_COMPOSE="/usr/local/bin/docker-compose"
COMPOSE_FILE="docker-compose.local.yml"
ENV_FILE=".env.production"
API_SERVICE="api"

cd "$PROJECT_ROOT"

echo "=== Deploying to Synology ==="
echo ""

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo "⚠ Warning: You have uncommitted changes"
    echo ""
    git status --short
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# 1. Run local build tests
echo "Step 1/5: Running build tests..."
./scripts/test-build.sh
echo ""

# 2. Push to GitHub
echo "Step 2/5: Pushing to GitHub..."
CURRENT_BRANCH=$(git branch --show-current)
git push origin "$CURRENT_BRANCH"
echo "  ✓ Pushed to origin/$CURRENT_BRANCH"
echo ""

# 3. Pull on Synology
echo "Step 3/5: Pulling on Synology..."
ssh "$SYNOLOGY_HOST" "cd $DEPLOY_PATH && $GIT_PATH pull origin $CURRENT_BRANCH"
echo "  ✓ Pulled latest code"
echo ""

# 4. Rebuild and restart containers
# COMPOSE_HTTP_TIMEOUT=300: Synology's docker-compose v1 default is 60s, which
# times out mid-recreate on multi-service rebuilds (leaving some containers on
# the old image). 300s gives the slow recreate room to finish.
echo "Step 4/5: Rebuilding containers..."
ssh "$SYNOLOGY_HOST" "export PATH=/usr/local/bin:\$PATH && export COMPOSE_HTTP_TIMEOUT=300 && cd $DEPLOY_PATH && $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE up -d --build"
echo ""

# 5. Run Alembic migrations, then verify the schema actually landed at head.
#
# #133 incident: a NAS deploy served new code on an old schema behind a green
# DB-free health probe (the container HEALTHCHECK only curls /health, which
# never touches the DB) — the migration had to be found and applied by hand
# after the fact. This tail ports the migration step deploy-demo.sh already
# runs (deploy-demo.sh:87) and adds a hard current-vs-heads check so a
# stuck/missed migration fails the deploy loudly instead of shipping green.
#
# If `alembic current` == `alembic heads` before this deploy (no pending
# migrations), `alembic upgrade head` is a no-op and the check below passes
# immediately — no behavior change beyond this cheap verification.
#
# COMPOSE_HTTP_TIMEOUT=300 here for the same reason as Step 4/5 (see above): a
# long DDL migration that outruns compose v1's 60s default would make `exec`
# return non-zero client-side while the migration is still running in the
# container — which would print the DEPLOY FAILED banner over a migration that
# actually succeeded. A false alarm here is as corrosive as a missed one.
echo "Step 5/5: Running database migrations..."
sleep 10
if ! ssh "$SYNOLOGY_HOST" "export PATH=/usr/local/bin:\$PATH && export COMPOSE_HTTP_TIMEOUT=300 && cd $DEPLOY_PATH && $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE exec -T $API_SERVICE python -m alembic upgrade head"; then
    echo ""
    echo "=========================================="
    echo "✗ DEPLOY FAILED: alembic upgrade head failed on the Synology host."
    echo "  The API container is already running the new code; the database may"
    echo "  now be in a partially-migrated state. Do NOT trust this deploy — SSH"
    echo "  in and inspect/fix the migration by hand (this is the #133 failure"
    echo "  mode: new code, old/broken schema, behind a green container)."
    echo "=========================================="
    exit 1
fi

CURRENT_REV=$(ssh "$SYNOLOGY_HOST" "export PATH=/usr/local/bin:\$PATH && export COMPOSE_HTTP_TIMEOUT=300 && cd $DEPLOY_PATH && $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE exec -T $API_SERVICE python -m alembic current" | awk 'NF { print $1; exit }')
HEAD_REV=$(ssh "$SYNOLOGY_HOST" "export PATH=/usr/local/bin:\$PATH && export COMPOSE_HTTP_TIMEOUT=300 && cd $DEPLOY_PATH && $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE exec -T $API_SERVICE python -m alembic heads" | awk 'NF { print $1; exit }')

if [ -z "$CURRENT_REV" ] || [ "$CURRENT_REV" != "$HEAD_REV" ]; then
    echo ""
    echo "=========================================="
    echo "✗ DEPLOY FAILED: schema is NOT at head after migration."
    echo "  alembic current: ${CURRENT_REV:-<none>}"
    echo "  alembic heads:   ${HEAD_REV:-<none>}"
    echo "  New code is running on a stale/mismatched schema — this is exactly"
    echo "  the #133 failure mode. The API container is UP; do NOT trust this"
    echo "  deploy. SSH in, run 'alembic upgrade head' by hand, and confirm"
    echo "  'alembic current' matches 'alembic heads' before treating this as done."
    echo "=========================================="
    exit 1
fi
echo "  ✓ Schema at head ($CURRENT_REV)"
echo ""

# Show status
echo "=== Container Status ==="
ssh "$SYNOLOGY_HOST" "export PATH=/usr/local/bin:\$PATH && export COMPOSE_HTTP_TIMEOUT=300 && cd $DEPLOY_PATH && $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE ps"
echo ""

echo "========================================="
echo "✓ Deployment complete!"
echo "========================================="
echo ""
echo "→ Frontend: http://$SYNOLOGY_HOST:3000"
echo "→ Backend:  http://$SYNOLOGY_HOST:8000"
echo ""
echo "Check logs with: ssh synology 'export PATH=/usr/local/bin:\$PATH && cd $DEPLOY_PATH && $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE logs -f'"
