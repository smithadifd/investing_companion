#!/bin/bash
# Test production build locally before deploying
# Run this before pushing to catch build errors early

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Use Node 20 if available via nvm
if [ -d "$HOME/.nvm/versions/node/v20.11.1" ]; then
    export PATH="$HOME/.nvm/versions/node/v20.11.1/bin:$PATH"
fi

echo "=== Testing Production Build ==="
echo "Using Node $(node --version)"
echo ""

# Frontend type check
echo "→ TypeScript check..."
cd frontend
npm run type-check
cd ..
echo "  ✓ TypeScript OK"
echo ""

# Frontend lint
echo "→ ESLint check..."
cd frontend
npm run lint
cd ..
echo "  ✓ ESLint OK"
echo ""

# Frontend tests
echo "→ Frontend tests (Vitest)..."
cd frontend
npm test
cd ..
echo "  ✓ Frontend tests OK"
echo ""

# Backend lint (if ruff is installed)
if command -v ruff &> /dev/null; then
    echo "→ Python lint (ruff)..."
    cd backend
    ruff check .
    cd ..
    echo "  ✓ Python OK"
    echo ""
else
    echo "→ Skipping Python lint (ruff not installed)"
    echo "  Install with: pip install ruff"
    echo ""
fi

# Build Docker images (without running)
echo "→ Building Docker images..."
if [ -f "docker-compose.local.yml" ]; then
    docker compose -f docker-compose.local.yml build
else
    docker compose -f docker-compose.prod.yml build
fi
echo "  ✓ Docker build OK"
echo ""

echo "========================================="
echo "✓ All build tests passed!"
echo "========================================="
echo ""
echo "Ready to deploy. Run: ./scripts/deploy-synology.sh"
