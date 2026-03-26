#!/usr/bin/env bash
set -euo pipefail

# ===========================================
# Investing Companion - Deploy to EC2 Demo
# ===========================================
# Usage: ./scripts/deploy-demo.sh

REMOTE="demo"
REMOTE_PATH="/opt/demos/investing_companion"
REPO_URL="https://github.com/smithadifd/investing_companion.git"
INFRA_DIR="${DEMO_INFRA_DIR:-$HOME/demo-infra}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# --- Ensure SSH access (auto-update security group if IP changed) ---
ensure_ssh_access() {
    if [ ! -f "$INFRA_DIR/terraform.tfvars" ]; then
        warn "demo-infra not found at $INFRA_DIR — skipping IP check"
        return 0
    fi

    local current_ip tfvars_ip
    current_ip=$(curl -s --max-time 5 ifconfig.me)
    tfvars_ip=$(grep 'admin_ip' "$INFRA_DIR/terraform.tfvars" | sed 's/.*"\(.*\)".*/\1/')

    if [[ "$current_ip" != "$tfvars_ip" ]]; then
        warn "Admin IP changed ($tfvars_ip -> $current_ip). Updating security group..."
        (cd "$INFRA_DIR" && ./update-ip.sh)
        info "Security group updated."
    else
        info "Admin IP unchanged ($current_ip)."
    fi
}

info "Deploying Investing Companion demo to EC2..."

ensure_ssh_access

# Clone or pull
ssh "$REMOTE" bash -s <<REMOTE_SCRIPT
set -euo pipefail

if [ ! -d "$REMOTE_PATH/.git" ]; then
    echo "Cloning repository..."
    sudo mkdir -p "$REMOTE_PATH"
    sudo chown ubuntu:ubuntu "$REMOTE_PATH"
    git clone "$REPO_URL" "$REMOTE_PATH"
else
    echo "Pulling latest changes..."
    cd "$REMOTE_PATH"
    git fetch origin main
    git reset --hard origin/main
fi

cd "$REMOTE_PATH"
echo "Now at commit: \$(git rev-parse --short HEAD)"

if [ ! -f ".env.demo" ]; then
    echo "ERROR: .env.demo not found at $REMOTE_PATH/.env.demo"
    echo "Create it with: SECRET_KEY=<secret> and POSTGRES_PASSWORD=<password>"
    exit 1
fi

echo ""
echo "--- Stopping all containers to free memory for build ---"
docker stop \$(docker ps -q) 2>/dev/null || true

echo "--- Building Docker images ---"
docker compose -f docker-compose.demo.yml --env-file .env.demo build

echo "--- Starting containers ---"
docker compose -f docker-compose.demo.yml --env-file .env.demo up -d
REMOTE_SCRIPT

info "Waiting for services to start..."
sleep 15

# Run Alembic migrations
ssh "$REMOTE" "cd $REMOTE_PATH && docker exec investing_demo_api python -m alembic upgrade head 2>/dev/null" || warn "Alembic migrations skipped (may already be up to date)"

# Seed demo data (ratios + macro events)
ssh "$REMOTE" "cd $REMOTE_PATH && docker exec investing_demo_api python -m scripts.seed_demo_data --all 2>/dev/null" || warn "Demo data seed skipped"

# Seed demo user + watchlists + trades + alerts
ssh "$REMOTE" "cd $REMOTE_PATH && docker exec investing_demo_api python -m scripts.seed_demo_users 2>/dev/null" || warn "Demo user seed skipped"

# Restart other demo services that were stopped for the build
info "Restarting other demo services..."
ssh "$REMOTE" bash -s <<'RESTART_SCRIPT'
for dir in /opt/demos/*/; do
    [ "$dir" = "/opt/demos/investing_companion/" ] && continue
    if [ -f "$dir/docker-compose.demo.yml" ] && [ -f "$dir/.env.demo" ]; then
        echo "Restarting $(basename $dir)..."
        (cd "$dir" && docker compose -f docker-compose.demo.yml --env-file .env.demo up -d) || true
    fi
done
echo ""
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
RESTART_SCRIPT

# Health checks
info "Checking health..."
if ssh "$REMOTE" "curl -sf --max-time 10 http://localhost:8003/health" > /dev/null 2>&1; then
    info "API health check passed"
else
    warn "API not responding yet"
fi
if ssh "$REMOTE" "curl -sf --max-time 10 -o /dev/null http://localhost:3013/" 2>&1; then
    info "Frontend health check passed"
else
    warn "Frontend not responding yet"
fi

info "Deploy complete. Demo at https://invest.smithadifd.com"
