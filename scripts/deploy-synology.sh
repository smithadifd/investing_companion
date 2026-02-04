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
echo "Step 1/4: Running build tests..."
./scripts/test-build.sh
echo ""

# 2. Push to GitHub
echo "Step 2/4: Pushing to GitHub..."
CURRENT_BRANCH=$(git branch --show-current)
git push origin "$CURRENT_BRANCH"
echo "  ✓ Pushed to origin/$CURRENT_BRANCH"
echo ""

# 3. Pull on Synology
echo "Step 3/4: Pulling on Synology..."
ssh "$SYNOLOGY_HOST" "cd $DEPLOY_PATH && $GIT_PATH pull origin $CURRENT_BRANCH"
echo "  ✓ Pulled latest code"
echo ""

# 4. Rebuild and restart containers
echo "Step 4/4: Rebuilding containers..."
ssh "$SYNOLOGY_HOST" "cd $DEPLOY_PATH && docker-compose -f docker-compose.local.yml up -d --build"
echo ""

# Show status
echo "=== Container Status ==="
ssh "$SYNOLOGY_HOST" "cd $DEPLOY_PATH && docker-compose -f docker-compose.local.yml ps"
echo ""

echo "========================================="
echo "✓ Deployment complete!"
echo "========================================="
echo ""
echo "→ Frontend: http://your-nas-ip:3000"
echo "→ Backend:  http://your-nas-ip:8000"
echo ""
echo "Check logs with: ssh synology 'cd $DEPLOY_PATH && docker-compose -f docker-compose.local.yml logs -f'"
