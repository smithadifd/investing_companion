#!/usr/bin/env bash
set -euo pipefail

SCRIPT="${1:-$(cd "$(dirname "$0")" && pwd)/deploy-demo.sh}"
SCRATCH=$(mktemp -d)
export DEMO_ROOT="$SCRATCH/demos" STUB_LOG="$SCRATCH/commands" HEALTH_FAIL="" BUILD_FAIL="" RESTORE_FAIL=""
export DB_NEVER_READY="" DB_READY_AFTER=0 MIGRATION_FAIL="" DATA_SEED_FAIL="" USER_SEED_FAIL=""
export DEMO_INFRA_DIR="$SCRATCH/infra"
mkdir -p "$SCRATCH/bin" "$DEMO_ROOT" "$DEMO_INFRA_DIR"
printf 'admin_ip = "127.0.0.1"\n' > "$DEMO_INFRA_DIR/terraform.tfvars"
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
elif [ "$1" = exec ]; then
    if [ "${3:-}" = pg_isready ]; then
        attempts_file="$DEMO_ROOT/db-attempts"
        attempts=$(cat "$attempts_file" 2>/dev/null || echo 0)
        attempts=$((attempts + 1))
        printf '%s\n' "$attempts" > "$attempts_file"
        [ -z "$DB_NEVER_READY" ] && [ "$attempts" -gt "$DB_READY_AFTER" ]
    elif [ "${4:-}" = -m ]; then
        case "${5:-}" in
            alembic) [ -z "$MIGRATION_FAIL" ] ;;
            scripts.seed_demo_data) [ -z "$DATA_SEED_FAIL" ] ;;
            scripts.seed_demo_users) [ -z "$USER_SEED_FAIL" ] ;;
        esac
    fi
elif [ "$1" = compose ]; then
    shift
    while [ "$1" != ps ] && [ "$1" != stop ] && [ "$1" != up ] && [ "$1" != build ] && [ "$1" != logs ]; do shift; done
    case "$1" in
        ps) [ -f .running ] && echo "$(basename "$PWD")-container" || true ;;
        stop) rm -f .running ;;
        up)
            if [ "${RESTORE_FAIL:-}" = "$(basename "$PWD")" ]; then exit 1; fi
            : > .running
            ;;
        build) [ -z "${BUILD_FAIL:-}" ] ;;
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
if [ "${1:-}" = -s ] && [ "${4:-}" = ifconfig.me ]; then echo 127.0.0.1; exit 0; fi
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
db_line=$(grep -n 'docker .* pg_isready ' "$STUB_LOG" | head -n 1 | cut -d: -f1)
migration_line=$(grep -n 'docker .* alembic upgrade head' "$STUB_LOG" | head -n 1 | cut -d: -f1)
[ -n "$db_line" ] && [ -n "$migration_line" ] && [ "$db_line" -lt "$migration_line" ] || fail 'database readiness did not precede migration'
printf 'PASS: only recorded demo projects are stopped and restored\n'
fi

if [ "$test_case" = all ] || [ "$test_case" = db_delayed ]; then
: > "$STUB_LOG"
export DB_READY_AFTER=2
if ! "$SCRIPT" > "$SCRATCH/db-delayed.out" 2>&1; then fail 'database becoming ready exited nonzero'; fi
[ "$(grep -c 'docker .* pg_isready ' "$STUB_LOG")" -eq 3 ] || fail 'database readiness did not retry until ready'
grep -q 'docker .* alembic upgrade head' "$STUB_LOG" || fail 'migration omitted after database became ready'
export DB_READY_AFTER=0
printf 'PASS: database becoming ready proceeds to migration\n'
fi

if [ "$test_case" = all ] || [ "$test_case" = db ]; then
: > "$STUB_LOG"
export DB_NEVER_READY=1
if "$SCRIPT" > "$SCRATCH/db-fail.out" 2>&1; then fail 'unready database exited zero'; fi
grep -q 'database not ready' "$SCRATCH/db-fail.out" || fail 'database readiness failure missing'
grep -q 'logs --tail=100 db' "$SCRATCH/db-fail.out" || fail 'database log hint missing'
[ "$(grep -c 'docker .* pg_isready ' "$STUB_LOG")" -eq 5 ] || fail 'database retry cap is not five attempts'
[ "$(grep '^sleep ' "$STUB_LOG" | tr '\n' ' ')" = 'sleep 1 sleep 2 sleep 4 sleep 8 ' ] || fail 'database retry backoff is incorrect'
if grep -q 'docker .* alembic upgrade head' "$STUB_LOG"; then fail 'migration ran without database readiness'; fi
if grep -q 'Deploy complete' "$SCRATCH/db-fail.out"; then fail 'unready database reported complete'; fi
[ -f "$DEMO_ROOT/running_demo/.running" ] || fail 'database failure did not restore running demo'
export DB_NEVER_READY=""
printf 'PASS: unready database fails before migration after bounded retries\n'
fi

if [ "$test_case" = all ] || [ "$test_case" = migration ]; then
: > "$STUB_LOG"
export MIGRATION_FAIL=1
if "$SCRIPT" > "$SCRATCH/migration-fail.out" 2>&1; then fail 'failed migration exited zero'; fi
grep -q 'Alembic migration failed' "$SCRATCH/migration-fail.out" || fail 'migration error missing'
if grep -q 'Deploy complete' "$SCRATCH/migration-fail.out"; then fail 'failed migration reported complete'; fi
if grep -q 'docker .* scripts.seed_demo_' "$STUB_LOG"; then fail 'seeds ran after failed migration'; fi
[ -f "$DEMO_ROOT/running_demo/.running" ] || fail 'failed migration did not restore running demo'
[ -f "$DEMO_ROOT/investing_companion/.running" ] || fail 'failed migration did not restore Investing Companion'
export MIGRATION_FAIL=""
printf 'PASS: failed migration exits nonzero with recorded demos restored\n'
fi

if [ "$test_case" = all ] || [ "$test_case" = data_seed ] || [ "$test_case" = user_seed ]; then
    if [ "$test_case" != user_seed ]; then
        : > "$STUB_LOG"
        export DATA_SEED_FAIL=1
        if "$SCRIPT" > "$SCRATCH/data-seed-fail.out" 2>&1; then fail 'failed data seed exited zero'; fi
        grep -q 'Demo data seed failed' "$SCRATCH/data-seed-fail.out" || fail 'data seed error missing'
        if grep -q 'Deploy complete' "$SCRATCH/data-seed-fail.out"; then fail 'failed data seed reported complete'; fi
        if grep -q 'docker .* scripts.seed_demo_users' "$STUB_LOG"; then fail 'user seed ran after failed data seed'; fi
        export DATA_SEED_FAIL=""
        printf 'PASS: failed data seed exits nonzero\n'
    fi
    if [ "$test_case" != data_seed ]; then
        : > "$STUB_LOG"
        export USER_SEED_FAIL=1
        if "$SCRIPT" > "$SCRATCH/user-seed-fail.out" 2>&1; then fail 'failed user seed exited zero'; fi
        grep -q 'Demo user seed failed' "$SCRATCH/user-seed-fail.out" || fail 'user seed error missing'
        if grep -q 'Deploy complete' "$SCRATCH/user-seed-fail.out"; then fail 'failed user seed reported complete'; fi
        export USER_SEED_FAIL=""
        printf 'PASS: failed user seed exits nonzero\n'
    fi
fi

if [ "$test_case" = all ] || [ "$test_case" = restore ]; then
: > "$STUB_LOG"
export RESTORE_FAIL=running_demo
if "$SCRIPT" > "$SCRATCH/restore-fail.out" 2>&1; then fail 'failed demo restart exited zero'; fi
grep -q "failed to restore demo project: $DEMO_ROOT/running_demo/" "$SCRATCH/restore-fail.out" || fail 'failed demo restart was not reported'
grep -q 'logs --tail=100' "$SCRATCH/restore-fail.out" || fail 'failed demo restart log command missing'
if grep -q 'Deploy complete' "$SCRATCH/restore-fail.out"; then fail 'failed demo restart reported complete'; fi
[ -f "$DEMO_ROOT/investing_companion/.running" ] || fail 'other recorded demo was not restored'
[ ! -f "$DEMO_ROOT/dormant_demo/.running" ] || fail 'dormant demo was started after restart failure'
export RESTORE_FAIL=""
printf 'PASS: failed demo restart exits nonzero and reports logs\n'
fi

if [ "$test_case" = all ] || [ "$test_case" = build ]; then
: > "$STUB_LOG"
: > "$DEMO_ROOT/running_demo/.running"
export BUILD_FAIL=1
if "$SCRIPT" > "$SCRATCH/build-fail.out" 2>&1; then fail 'failed build exited zero'; fi
[ -f "$DEMO_ROOT/running_demo/.running" ] || fail 'failed build did not restore running demo'
[ -f "$DEMO_ROOT/investing_companion/.running" ] || fail 'failed build did not restore Investing Companion'
[ ! -f "$DEMO_ROOT/dormant_demo/.running" ] || fail 'failed build started dormant demo'
if grep -q 'Deploy complete' "$SCRATCH/build-fail.out"; then fail 'failed build reported complete'; fi
export BUILD_FAIL=""
printf 'PASS: failed build restores recorded demos and exits nonzero\n'
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
