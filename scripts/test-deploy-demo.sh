#!/usr/bin/env bash
set -euo pipefail

SCRIPT="${1:-$(cd "$(dirname "$0")" && pwd)/deploy-demo.sh}"
SCRATCH=$(mktemp -d)
export DEMO_ROOT="$SCRATCH/demos" STUB_LOG="$SCRATCH/commands" HEALTH_FAIL=""
export DEMO_INFRA_DIR="$SCRATCH/infra"
mkdir -p "$SCRATCH/bin" "$DEMO_ROOT" "$DEMO_INFRA_DIR"
: > "$STUB_LOG"
for project in investing_companion running_demo dormant_demo; do
    mkdir -p "$DEMO_ROOT/$project/.git"
    : > "$DEMO_ROOT/$project/.env.demo"
    : > "$DEMO_ROOT/$project/docker-compose.demo.yml"
done
: > "$DEMO_ROOT/investing_companion/.running"
: > "$DEMO_ROOT/running_demo/.running"
: > "$SCRATCH/non-demo-running"

cat > "$SCRATCH/bin/ssh" <<'STUB'
#!/usr/bin/env bash
printf 'ssh %s\n' "$*" >> "$STUB_LOG"
if [ "${2:-}" = bash ] && [ "${3:-}" = -s ]; then
    sed "s@/opt/demos@$DEMO_ROOT@g" | bash -s
fi
STUB
cat > "$SCRATCH/bin/docker" <<'STUB'
#!/usr/bin/env bash
printf 'docker %s %s\n' "$PWD" "$*" >> "$STUB_LOG"
if [ "$1" = ps ]; then
    echo non-demo-container-id
elif [ "$1" = compose ]; then
    shift
    while [ "$1" != ps ] && [ "$1" != stop ] && [ "$1" != up ] && [ "$1" != build ] && [ "$1" != logs ]; do shift; done
    case "$1" in
        ps) [ -f .running ] && echo "$(basename "$PWD")-container" || true ;;
        stop) rm -f .running ;;
        up) : > .running ;;
    esac
fi
STUB
cat > "$SCRATCH/bin/git" <<'STUB'
#!/usr/bin/env bash
printf 'git %s\n' "$*" >> "$STUB_LOG"
if [ "${1:-}" = rev-parse ]; then echo abc123; fi
STUB
cat > "$SCRATCH/bin/curl" <<'STUB'
#!/usr/bin/env bash
printf 'curl %s\n' "$*" >> "$STUB_LOG"
case "$*" in *"$HEALTH_FAIL"*) [ -z "$HEALTH_FAIL" ] ;; *) exit 0 ;; esac
STUB
cat > "$SCRATCH/bin/sleep" <<'STUB'
#!/usr/bin/env bash
printf 'sleep %s\n' "$*" >> "$STUB_LOG"
STUB
cat > "$SCRATCH/bin/sudo" <<'STUB'
#!/usr/bin/env bash
printf 'sudo %s\n' "$*" >> "$STUB_LOG"
STUB
chmod +x "$SCRATCH/bin/"*
export PATH="$SCRATCH/bin:$PATH"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
assert_no_global_stop() {
    if grep -q '^docker .* stop non-demo-container-id' "$STUB_LOG"; then
        fail 'a non-demo container was stopped'
    fi
}

test_case="${DEPLOY_TEST_CASE:-all}"
if [ "$test_case" = all ] || [ "$test_case" = scope ]; then
"$SCRIPT" > "$SCRATCH/success.out" 2>&1 || fail 'successful deploy exited nonzero'
assert_no_global_stop
[ -f "$SCRATCH/non-demo-running" ] || fail 'non-demo container was changed'
[ -f "$DEMO_ROOT/running_demo/.running" ] || fail 'running demo was not restarted'
[ ! -f "$DEMO_ROOT/dormant_demo/.running" ] || fail 'dormant demo was started'
grep -q 'both health checks passed' "$SCRATCH/success.out" || fail 'success health result missing'
printf 'PASS: only recorded demo projects are stopped and restored\n'
fi

if [ "$test_case" = all ] || [ "$test_case" = api ]; then
: > "$STUB_LOG"
export HEALTH_FAIL='8003/health'
if "$SCRIPT" > "$SCRATCH/api-fail.out" 2>&1; then fail 'failed API health check exited zero'; fi
grep -q 'health check failed: http://localhost:8003/health' "$SCRATCH/api-fail.out" || fail 'failed API URL missing'
grep -q 'logs --tail=100 api' "$SCRATCH/api-fail.out" || fail 'API log command missing'
[ "$(grep -c 'curl .*8003/health' "$STUB_LOG")" -eq 5 ] || fail 'API retry cap is not five attempts'
[ "$(grep '^sleep ' "$STUB_LOG" | tr '\n' ' ')" = 'sleep 1 sleep 2 sleep 4 sleep 8 ' ] || fail 'API retry backoff is incorrect'
tail -n 1 "$SCRATCH/api-fail.out" | grep -q 'Deploy failed: http://localhost:8003/health' || fail 'final API failure line missing'
printf 'PASS: API health failure exits nonzero after retries with logs\n'
fi

if [ "$test_case" = all ] || [ "$test_case" = frontend ]; then
: > "$STUB_LOG"
export HEALTH_FAIL='3013/'
if "$SCRIPT" > "$SCRATCH/frontend-fail.out" 2>&1; then fail 'failed frontend health check exited zero'; fi
grep -q 'health check failed: http://localhost:3013/' "$SCRATCH/frontend-fail.out" || fail 'failed frontend URL missing'
grep -q 'logs --tail=100 frontend' "$SCRATCH/frontend-fail.out" || fail 'frontend log command missing'
tail -n 1 "$SCRATCH/frontend-fail.out" | grep -q 'Deploy failed: http://localhost:3013/' || fail 'final frontend failure line missing'
printf 'PASS: frontend health failure exits nonzero with logs\n'
fi

if [ "$test_case" = all ] || [ "$test_case" = dry_run ]; then
: > "$STUB_LOG"
"$SCRIPT" --dry-run > "$SCRATCH/dry-run.out" || fail 'dry run exited nonzero'
[ ! -s "$STUB_LOG" ] || fail 'dry run invoked remote or network command'
grep -q 'compose stop' "$SCRATCH/dry-run.out" || fail 'dry run omitted remote plan'
printf 'PASS: dry run prints plan without remote commands\n'
fi
