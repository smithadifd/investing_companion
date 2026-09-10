#!/bin/bash
# Regression tests for scripts/deploy-recomputer.sh and the RETIRED guard on
# scripts/deploy-synology.sh (CM6 findings F2, F4, F5).
#
# Plain bash + assertions, matching this repo's existing scripts/test-build.sh
# convention — there is no shell test framework (bats, shunit2, etc.) in use
# here, so this does not introduce one.
#
# Seam under test: each script's own CLI surface (--dry-run / bare invocation,
# exit code, and which external binaries it does or does not invoke). No
# internal function is sourced or called directly; every assertion runs the
# real script as a subprocess through its documented entry point.
#
# Safety: every invocation below stubs ssh/scp/rsync/curl/docker/docker-compose
# on PATH (each stub logs its invocation and exits 99) BEFORE running either
# script, so even a regression that reintroduced a live network/host call
# would be caught by a non-99 "unexpected" failure or a populated invocation
# log — never a real ssh, scp, rsync, curl, docker, or docker-compose call.
#
# Usage: ./scripts/test-deploy-recomputer.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

STUBDIR="$WORKDIR/stubs"
INVOKED_LOG="$WORKDIR/invoked.log"
mkdir -p "$STUBDIR"

for bin in ssh scp rsync curl docker docker-compose; do
    cat > "$STUBDIR/$bin" <<STUB
#!/bin/bash
echo "\$0 \$*" >> "$INVOKED_LOG"
exit 99
STUB
    chmod +x "$STUBDIR/$bin"
done

PASS=0
FAIL=0

check() {
    local desc="$1" ok="$2"
    if [ "$ok" -eq 0 ]; then
        echo "  ok - $desc"
        PASS=$((PASS + 1))
    else
        echo "  NOT OK - $desc"
        FAIL=$((FAIL + 1))
    fi
}

assert_no_stub_invoked() {
    local desc="$1"
    if [ -s "$INVOKED_LOG" ]; then
        echo "  NOT OK - $desc"
        echo "    stub log was NOT empty:"
        sed 's/^/      /' "$INVOKED_LOG"
        FAIL=$((FAIL + 1))
    else
        echo "  ok - $desc"
        PASS=$((PASS + 1))
    fi
}

echo "=== test-deploy-recomputer.sh ==="
echo ""

# --- Test 1: --dry-run reaches no host --------------------------------------
echo "-- dry-run reaches no host --"
: > "$INVOKED_LOG"
OUT_1="$(PATH="$STUBDIR:$PATH" bash scripts/deploy-recomputer.sh --dry-run 2>&1)"
EXIT_1=$?
check "exit code is 0 (got $EXIT_1)" "$([ "$EXIT_1" -eq 0 ] && echo 0 || echo 1)"
assert_no_stub_invoked "no ssh/scp/rsync/curl/docker/docker-compose invoked"
echo "$OUT_1" | grep -q "No ssh invoked, no host reached." \
    && check "plan text says no ssh/no host reached" 0 \
    || check "plan text says no ssh/no host reached" 1
echo ""

# --- Test 2: plan text names the build step (F1) -----------------------------
echo "-- plan text names the build step --"
echo "$OUT_1" | grep -q -- "--build" \
    && check "plan text contains --build" 0 \
    || check "plan text contains --build" 1
echo "$OUT_1" | grep -q "api, celery_worker, celery_beat, frontend" \
    && check "plan text names the four build-only services" 0 \
    || check "plan text names the four build-only services" 1
echo ""

# --- Test 3: hostile branch name is refused, not executed (F2) --------------
echo "-- hostile branch name refused --"
GITSTUBDIR="$WORKDIR/gitstub"
mkdir -p "$GITSTUBDIR"
HOSTILE_BRANCH='main;touch${IFS}/tmp/pwn-deploy-recomputer-test'
cat > "$GITSTUBDIR/git" <<GITSTUB
#!/bin/bash
if [ "\$1" = "branch" ] && [ "\$2" = "--show-current" ]; then
    printf '%s\n' '$HOSTILE_BRANCH'
    exit 0
fi
exec /usr/bin/git "\$@"
GITSTUB
chmod +x "$GITSTUBDIR/git"

: > "$INVOKED_LOG"
rm -f /tmp/pwn-deploy-recomputer-test
OUT_3="$(PATH="$GITSTUBDIR:$STUBDIR:$PATH" bash scripts/deploy-recomputer.sh --dry-run 2>&1)"
EXIT_3=$?
check "exit code is non-zero (got $EXIT_3)" "$([ "$EXIT_3" -ne 0 ] && echo 0 || echo 1)"
echo "$OUT_3" | grep -q "Refusing to deploy: branch name fails the safety allowlist" \
    && check "refusal message printed" 0 \
    || check "refusal message printed" 1
assert_no_stub_invoked "no ssh/scp/rsync/curl/docker/docker-compose invoked for the hostile branch"
if [ -e /tmp/pwn-deploy-recomputer-test ]; then
    check "injected command did NOT execute" 1
    rm -f /tmp/pwn-deploy-recomputer-test
else
    check "injected command did NOT execute" 0
fi
echo ""

# --- Test 4: deploy-synology.sh refuses without the override (F4) -----------
echo "-- retired Synology script refuses by default --"
: > "$INVOKED_LOG"
OUT_4="$(PATH="$STUBDIR:$PATH" bash scripts/deploy-synology.sh 2>&1)"
EXIT_4=$?
check "exit code is non-zero (got $EXIT_4)" "$([ "$EXIT_4" -ne 0 ] && echo 0 || echo 1)"
echo "$OUT_4" | grep -q "RETIRED" \
    && check "RETIRED message printed" 0 \
    || check "RETIRED message printed" 1
assert_no_stub_invoked "no ssh/scp/rsync/curl/docker/docker-compose invoked (guard fires before the network)"
echo ""

echo "========================================="
echo "PASS: $PASS  FAIL: $FAIL"
echo "========================================="

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi
exit 0
