#!/usr/bin/env bash
#
# deploy.sh — rebuild (optional) and redeploy the MTracker docker service,
# then verify it is actually serving the new code.
#
# Usage:
#   ./deploy.sh                # rebuild image + redeploy + verify (default)
#   ./deploy.sh --no-build     # restart only, no rebuild
#   ./deploy.sh --logs         # follow logs after a successful deploy
#   ./deploy.sh --timeout 120  # seconds to wait for readiness (default 90)
#
set -euo pipefail

cd "$(dirname "$0")"

# sudo is needed for docker on this host; skip it when already root.
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

REBUILD=1
FOLLOW_LOGS=0
TIMEOUT=90

while [ $# -gt 0 ]; do
    case "$1" in
        --no-build) REBUILD=0; shift ;;
        --logs) FOLLOW_LOGS=1; shift ;;
        --timeout) TIMEOUT="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,11p' "$0"
            exit 0
            ;;
        *) echo "Unknown flag: $1 (see --help)" >&2; exit 1 ;;
    esac
done

COMPOSE_FILE="docker-compose.yml"
SERVICE="mtracker"
BASE_URL="http://127.0.0.1"

fail() { echo "ERROR: $*" >&2; exit 1; }

# ── Preflight ──────────────────────────────────────────
command -v docker >/dev/null 2>&1 || fail "docker not found in PATH"
[ -f "$COMPOSE_FILE" ] || fail "$COMPOSE_FILE not found (run from project root)"
$SUDO docker compose version >/dev/null 2>&1 || fail "'docker compose' is not available"

# ── Deploy ─────────────────────────────────────────────
echo "==> Deploying $SERVICE (rebuild=$REBUILD)…"
if [ "$REBUILD" -eq 1 ]; then
    $SUDO docker compose up -d --build
else
    $SUDO docker compose up -d --no-build "$SERVICE"
fi

# ── Wait for readiness ─────────────────────────────────
echo "==> Waiting for service (timeout ${TIMEOUT}s)…"
deadline=$((SECONDS + TIMEOUT))
while true; do
    if curl -fs -o /dev/null --max-time 5 "$BASE_URL/login" 2>/dev/null; then
        echo "    login page responding."
        break
    fi
    if [ $SECONDS -ge "$deadline" ]; then
        echo "    readiness timeout — last logs:" >&2
        $SUDO docker compose logs --tail=50 "$SERVICE" >&2 || true
        fail "service did not become ready in ${TIMEOUT}s"
    fi
    sleep 3
done

# ── Verify ─────────────────────────────────────────────
echo "==> Verifying…"
$SUDO docker compose ps "$SERVICE"

check() { # check <desc> <expected-code> <url> [curl-args...]
    local desc="$1" expected="$2" url="$3"; shift 3
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$@" "$url")
    if [ "$code" = "$expected" ]; then
        echo "    OK   [$code] $desc"
    else
        fail "$desc: expected HTTP $expected, got $code ($url)"
    fi
}

check "login page"            200 "$BASE_URL/login"
check "MCP SSE requires auth (new code live)" 401 "$BASE_URL/api/mcp/sse"
check "API keys page requires login (route registered)" 302 "$BASE_URL/api-keys"
check "MCP help page requires login (route registered)" 302 "$BASE_URL/mcp-help"

echo "==> Deploy successful."
$SUDO docker compose logs --tail=15 "$SERVICE" || true

if [ "$FOLLOW_LOGS" -eq 1 ]; then
    echo "==> Following logs (Ctrl+C to stop)…"
    $SUDO docker compose logs -f "$SERVICE"
fi
