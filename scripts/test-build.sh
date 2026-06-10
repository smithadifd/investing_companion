#!/bin/bash
# Test production build locally before deploying
# Run this before pushing to catch build errors early

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Match the repo's pinned Node (.nvmrc = 22). The frontend test suite pulls in
# jsdom's html-encoding-sniffer, which require()s the ESM-only @exodus/bytes —
# that fails on Node <22 with ERR_REQUIRE_ESM. Node 22 supports require(ESM),
# and CI/Docker both run 22, so pin local pre-flight to the same.
if [ -s "$HOME/.nvm/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.nvm/nvm.sh"
    nvm use >/dev/null 2>&1 || nvm use 22 >/dev/null 2>&1 || true
fi

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if [ "$NODE_MAJOR" -lt 22 ]; then
    echo "✗ Node $NODE_MAJOR detected; this project requires Node 22+ (see .nvmrc)."
    echo "  The frontend test suite fails on Node <22 (ERR_REQUIRE_ESM in html-encoding-sniffer)."
    exit 1
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
