#!/bin/bash
# Deploy Investing Companion demo to EC2
set -e

DEMO_HOST="demo"
DEPLOY_PATH="/opt/demos/investing_companion"

echo "=== Deploying IC Demo to EC2 ==="

# Clone or pull
ssh "$DEMO_HOST" "
  if [ ! -d $DEPLOY_PATH ]; then
    git clone https://github.com/smithadifd/investing_companion.git $DEPLOY_PATH
  else
    cd $DEPLOY_PATH && git pull origin main
  fi
"

# Build and start containers
ssh "$DEMO_HOST" "
  cd $DEPLOY_PATH
  docker compose -f docker-compose.demo.yml --env-file .env.demo up -d --build
"

echo ""
echo "Waiting for services to start..."
sleep 15

# Run Alembic migrations
ssh "$DEMO_HOST" "
  cd $DEPLOY_PATH
  docker exec investing_demo_api python -m alembic upgrade head 2>/dev/null || echo 'Alembic migrations skipped (may already be up to date)'
"

# Seed demo data (ratios + macro events)
ssh "$DEMO_HOST" "
  cd $DEPLOY_PATH
  docker exec investing_demo_api python -m scripts.seed_demo_data --all 2>/dev/null || echo 'Demo data seed skipped'
"

# Seed demo user + watchlists + trades + alerts
ssh "$DEMO_HOST" "
  cd $DEPLOY_PATH
  docker exec investing_demo_api python -m scripts.seed_demo_users 2>/dev/null || echo 'Demo user seed skipped'
"

# Health check
echo ""
echo "Checking health..."
ssh "$DEMO_HOST" "curl -sf http://localhost:8003/health" && echo " API healthy" || echo " API not responding yet"
ssh "$DEMO_HOST" "curl -sf -o /dev/null -w '%{http_code}' http://localhost:3013/" && echo " Frontend healthy" || echo " Frontend not responding yet"

echo ""
echo "=== IC Demo deployment complete ==="
echo "https://invest.smithadifd.com"
