#!/usr/bin/env bash
set -euo pipefail

# Deploy the public demo to EC2. This runs Alembic migrations and reseeds demo
# data and the demo user; those operations write to the demo database.
# Usage: ./scripts/deploy-demo.sh [--dry-run]

REMOTE="demo"
INFRA_DIR="${DEMO_INFRA_DIR:-$HOME/demo-infra}"

info() { printf '[INFO] %s\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1"; }

ensure_ssh_access() {
    if [ ! -f "$INFRA_DIR/terraform.tfvars" ]; then
        warn "demo-infra not found at $INFRA_DIR — skipping IP check"
        return 0
    fi

    local current_ip tfvars_ip
    current_ip=$(curl -s --max-time 5 ifconfig.me)
    tfvars_ip=$(sed -n 's/.*admin_ip.*"\(.*\)".*/\1/p' "$INFRA_DIR/terraform.tfvars")
    if [[ "$current_ip" != "$tfvars_ip" ]]; then
        warn "Admin IP changed ($tfvars_ip -> $current_ip). Updating security group..."
        (cd "$INFRA_DIR" && ./update-ip.sh)
        info "Security group updated."
    else
        info "Admin IP unchanged ($current_ip)."
    fi
}

remote_script() {
cat <<'REMOTE_SCRIPT'
set -euo pipefail

DEMO_ROOT="${DEMO_ROOT:-/opt/demos}"
REMOTE_PATH="$DEMO_ROOT/investing_companion"
REPO_URL="https://github.com/smithadifd/investing_companion.git"
compose() { docker compose -f docker-compose.demo.yml --env-file .env.demo "$@"; }

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
echo "Now at commit: $(git rev-parse --short HEAD)"
if [ ! -f .env.demo ]; then
    echo "ERROR: .env.demo not found at $REMOTE_PATH/.env.demo" >&2
    exit 1
fi

# Record only running projects whose compose file and environment live under DEMO_ROOT.
running_projects=()
for dir in "$DEMO_ROOT"/*/; do
    [ -f "$dir/docker-compose.demo.yml" ] && [ -f "$dir/.env.demo" ] || continue
    if [ -n "$(cd "$dir" && compose ps -q)" ]; then
        running_projects+=("$dir")
    fi
done

restore_stopped() {
    local dir failed=0
    for dir in "${running_projects[@]}"; do
        echo "Restoring demo project: $dir"
        if ! (cd "$dir" && compose up -d); then
            echo "ERROR: failed to restore demo project: $dir" >&2
            echo "Inspect logs: cd $dir && docker compose -f docker-compose.demo.yml --env-file .env.demo logs --tail=100" >&2
            failed=1
        fi
    done
    return "$failed"
}
restored=0
on_exit() {
    local status=$?
    trap - EXIT
    if [ "$restored" -eq 0 ]; then
        restore_stopped || status=1
    fi
    exit "$status"
}
trap on_exit EXIT

echo "--- Stopping running demo projects to free memory for build ---"
for dir in "${running_projects[@]}"; do
    echo "Stopping demo project: $dir"
    (cd "$dir" && compose stop)
done

cd "$REMOTE_PATH"
echo "--- Building Docker images ---"
compose build
echo "--- Starting Investing Companion ---"
compose up -d

# Restore every project recorded before the build, including this one if it ran.
restored=1
restore_stopped

echo "--- Waiting for demo database ---"
for attempt in 1 2 3 4 5; do
    if docker exec investing_demo_db pg_isready -U investing_demo -d investing_demo >/dev/null 2>&1; then
        break
    fi
    if [ "$attempt" -eq 5 ]; then
        echo "ERROR: database not ready after five attempts" >&2
        echo "Inspect logs: cd $REMOTE_PATH && docker compose -f docker-compose.demo.yml --env-file .env.demo logs --tail=100 db" >&2
        exit 1
    fi
    sleep "$((2 ** (attempt - 1)))"
done

if ! docker exec investing_demo_api python -m alembic upgrade head; then
    echo "ERROR: Alembic migration failed" >&2
    exit 1
fi
if ! docker exec investing_demo_api python -m scripts.seed_demo_data --all; then
    echo "ERROR: Demo data seed failed" >&2
    exit 1
fi
if ! docker exec investing_demo_api python -m scripts.seed_demo_users; then
    echo "ERROR: Demo user seed failed" >&2
    exit 1
fi

check_health() {
    local url="$1" log_service="$2" attempt delay
    for attempt in 1 2 3 4 5; do
        if curl -fsS --max-time 10 -o /dev/null "$url"; then
            echo "Health check passed: $url"
            return 0
        fi
        if [ "$attempt" -lt 5 ]; then
            delay=$((2 ** (attempt - 1)))
            sleep "$delay"
        fi
    done
    echo "ERROR: health check failed: $url" >&2
    echo "Inspect logs: cd $REMOTE_PATH && docker compose -f docker-compose.demo.yml --env-file .env.demo logs --tail=100 $log_service" >&2
    echo "Deploy failed: $url" >&2
    return 1
}

check_health http://localhost:8003/health api
check_health http://localhost:3013/ frontend
printf 'Deploy complete. Demo at https://invest.smithadifd.com; both health checks passed.\n'
REMOTE_SCRIPT
}

if [ "${1:-}" = "--dry-run" ] && [ "$#" -eq 1 ]; then
    printf 'Remote plan for %s (no SSH or local network changes):\n' "$REMOTE"
    remote_script
    exit 0
fi
if [ "$#" -ne 0 ]; then
    printf 'Usage: %s [--dry-run]\n' "$0" >&2
    exit 2
fi

info "Deploying Investing Companion demo to EC2..."
ensure_ssh_access
remote_script | ssh "$REMOTE" bash -s
