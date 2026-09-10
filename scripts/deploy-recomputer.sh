#!/bin/bash
# Deploy Investing Companion to reComputer (prod).
#
# Usage:
#   ./scripts/deploy-recomputer.sh --dry-run   # print plan; no changes, no ssh
#   ./scripts/deploy-recomputer.sh             # live deploy (supervised)
#
# --dry-run is the verifiable seam: it prints the host, project dir, compose
# pull + up, /health poll, and rollback target, then exits 0 without invoking
# ssh or reaching any host.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Configuration
REMOTE_HOST="recomputer"
DEPLOY_PATH="/home/fivefootfive/investing_companion"
COMPOSE_FILE="docker-compose.local.yml"
COMPOSE_OVERRIDE="docker-compose.recomputer.yml"
ENV_FILE=".env.production"
API_SERVICE="api"
HEALTH_URL="http://localhost:8000/health"
HEALTH_ATTEMPTS=10
HEALTH_SLEEP=3

cd "$PROJECT_ROOT"

DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help)
            echo "Usage: $0 [--dry-run]"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--dry-run]"
            exit 1
            ;;
    esac
done

CURRENT_BRANCH=$(git branch --show-current)

compose_cmd() {
    echo "docker compose -f $COMPOSE_FILE -f $COMPOSE_OVERRIDE --env-file $ENV_FILE $*"
}

print_plan() {
    echo "=== DRY-RUN: Investing Companion → reComputer (no changes, no network) ==="
    echo ""
    echo "Host:          $REMOTE_HOST"
    echo "Project dir:   $DEPLOY_PATH"
    echo "Branch:        $CURRENT_BRANCH"
    echo "Compose:       $(compose_cmd '<subcommand>')"
    echo "Health poll:   $HEALTH_URL"
    echo "Rollback:      last-known-good commit = remote HEAD captured before pull"
    echo ""
    echo "Plan:"
    echo "  1. Capture rollback target (git rev-parse HEAD on $REMOTE_HOST:$DEPLOY_PATH)"
    echo "  2. git pull origin $CURRENT_BRANCH in $DEPLOY_PATH"
    echo "  3. $(compose_cmd pull)"
    echo "  4. $(compose_cmd up -d)"
    echo "  5. alembic upgrade head + current-vs-heads check ($API_SERVICE)"
    echo "  6. Poll /health until healthy ($HEALTH_ATTEMPTS attempts, ${HEALTH_SLEEP}s apart)"
    echo "  7. On failure: git reset --hard <last-known-good> && $(compose_cmd up -d)"
    echo ""
    echo "Dry-run complete. No ssh invoked, no host reached."
}

if [ "$DRY_RUN" -eq 1 ]; then
    print_plan
    exit 0
fi

# --- live path below: never reached by --dry-run ---

echo "=== Deploying to reComputer ==="
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

remote() {
    ssh "$REMOTE_HOST" "cd $DEPLOY_PATH && $*"
}

remote_compose() {
    ssh "$REMOTE_HOST" "cd $DEPLOY_PATH && docker compose -f $COMPOSE_FILE -f $COMPOSE_OVERRIDE --env-file $ENV_FILE $*"
}

rollback() {
    local reason="$1"
    echo ""
    echo "=========================================="
    echo "✗ DEPLOY FAILED: $reason"
    echo "  Rolling back to last-known-good $PREV"
    echo "=========================================="
    if ! remote "git reset --hard $PREV"; then
        echo "✗ Rollback git reset failed. Box may be in a mixed state — inspect by hand."
        exit 1
    fi
    if ! remote_compose up -d; then
        echo "✗ Rollback compose up failed. Box may be in a mixed state — inspect by hand."
        exit 1
    fi
    echo "  ✓ Rolled back to $PREV"
    echo "  Code rollback does not reverse Alembic DDL. If step 5 ran, inspect schema by hand."
    exit 1
}

# 1. Capture last-known-good commit BEFORE changing the box.
echo "Step 1/6: Capturing last-known-good commit on $REMOTE_HOST..."
PREV=$(ssh "$REMOTE_HOST" "cd $DEPLOY_PATH && git rev-parse HEAD")
if [ -z "$PREV" ]; then
    echo "✗ Could not read remote HEAD — refusing to deploy (cannot roll back what we cannot pin)."
    exit 1
fi
echo "  ✓ Rollback target: $PREV"
echo ""

# 2. Pull on reComputer
echo "Step 2/6: Pulling on reComputer..."
if ! remote "git pull origin $CURRENT_BRANCH"; then
    rollback "git pull origin $CURRENT_BRANCH failed on $REMOTE_HOST"
fi
echo "  ✓ Pulled latest code"
echo ""

# 3. compose pull
echo "Step 3/6: docker compose pull..."
if ! remote_compose pull; then
    rollback "docker compose pull failed on $REMOTE_HOST"
fi
echo "  ✓ Images pulled"
echo ""

# 4. compose up
echo "Step 4/6: docker compose up -d..."
if ! remote_compose up -d; then
    rollback "docker compose up -d failed on $REMOTE_HOST"
fi
echo "  ✓ Containers up"
echo ""

# 5. Run Alembic migrations, then verify the schema actually landed at head.
#
# #133 incident: a deploy served new code on an old schema behind a green
# DB-free health probe (the container HEALTHCHECK only curls /health, which
# never touches the DB) — the migration had to be found and applied by hand
# after the fact. This tail ports the migration step deploy-synology.sh /
# deploy-demo.sh already run and adds a hard current-vs-heads check so a
# stuck/missed migration fails the deploy loudly instead of shipping green.
echo "Step 5/6: Running database migrations..."
sleep 10
if ! remote_compose exec -T "$API_SERVICE" python -m alembic upgrade head; then
    rollback "alembic upgrade head failed on $REMOTE_HOST"
fi

CURRENT_REV=$(remote_compose exec -T "$API_SERVICE" python -m alembic current | awk 'NF { print $1; exit }')
HEAD_REV=$(remote_compose exec -T "$API_SERVICE" python -m alembic heads | awk 'NF { print $1; exit }')

if [ -z "$CURRENT_REV" ] || [ "$CURRENT_REV" != "$HEAD_REV" ]; then
    echo "  alembic current: ${CURRENT_REV:-<none>}"
    echo "  alembic heads:   ${HEAD_REV:-<none>}"
    rollback "schema is NOT at head after migration"
fi
echo "  ✓ Schema at head ($CURRENT_REV)"
echo ""

# 6. Health poll
echo "Step 6/6: Polling /health at $HEALTH_URL..."
HEALTHY=0
for i in $(seq 1 "$HEALTH_ATTEMPTS"); do
    if ssh "$REMOTE_HOST" "curl -sf --max-time 5 $HEALTH_URL" >/dev/null; then
        HEALTHY=1
        echo "  ✓ /health passed on attempt $i"
        break
    fi
    echo "  attempt $i/$HEALTH_ATTEMPTS failed; retrying in ${HEALTH_SLEEP}s..."
    sleep "$HEALTH_SLEEP"
done
if [ "$HEALTHY" -ne 1 ]; then
    rollback "/health poll failed after $HEALTH_ATTEMPTS attempts"
fi
echo ""

# Show status
echo "=== Container Status ==="
remote_compose ps
echo ""

echo "========================================="
echo "✓ Deployment complete!"
echo "========================================="
echo ""
echo "→ Host:     $REMOTE_HOST"
echo "→ Path:     $DEPLOY_PATH"
echo "→ Health:   $HEALTH_URL"
echo "→ Rollback target was: $PREV"
echo ""
echo "Check logs with: ssh $REMOTE_HOST 'cd $DEPLOY_PATH && $(compose_cmd logs -f)'"
