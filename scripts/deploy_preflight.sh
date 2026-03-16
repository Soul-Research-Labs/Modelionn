#!/usr/bin/env bash
set -euo pipefail

# Validate production deployment prerequisites before running docker compose up.
# Usage:
#   ./scripts/deploy_preflight.sh
#   ./scripts/deploy_preflight.sh .env.prod

ENV_FILE="${1:-.env}"
BASE_COMPOSE="docker-compose.yml"
PROD_COMPOSE="docker-compose.prod.yml"

fail() {
  echo "[FAIL] $1" >&2
  exit 1
}

warn() {
  echo "[WARN] $1"
}

pass() {
  echo "[OK]   $1"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

check_required_var() {
  local key="$1"
  local value="${!key:-}"
  if [[ -z "$value" ]]; then
    fail "Missing required env var: $key"
  fi
}

check_secret_length() {
  local key="$1"
  local min_len="$2"
  local value="${!key:-}"
  local len=${#value}
  if (( len < min_len )); then
    fail "$key must be at least $min_len characters (got $len)"
  fi
}

check_not_default_secret() {
  local key="$1"
  local value="${!key:-}"
  local lower
  lower=$(echo "$value" | tr '[:upper:]' '[:lower:]')

  case "$lower" in
    changeme|change-me|default|secret|password|modelionn-secret|dev-secret|test-secret)
      fail "$key appears to use a default/insecure value"
      ;;
  esac
}

echo "==> Modelionn production preflight"

require_cmd docker
if ! docker compose version >/dev/null 2>&1; then
  fail "Docker Compose v2 is required"
fi
pass "Docker and Docker Compose are available"

[[ -f "$BASE_COMPOSE" ]] || fail "Missing $BASE_COMPOSE"
[[ -f "$PROD_COMPOSE" ]] || fail "Missing $PROD_COMPOSE"
pass "Compose files are present"

[[ -f "$ENV_FILE" ]] || fail "Missing env file: $ENV_FILE"
pass "Env file found: $ENV_FILE"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

check_required_var POSTGRES_PASSWORD
check_required_var REDIS_PASSWORD
check_required_var MODELIONN_SECRET_KEY
check_required_var NEXTAUTH_SECRET
check_required_var FLOWER_PASSWORD
check_required_var CORS_ORIGINS
check_required_var NEXTAUTH_URL
pass "Required environment variables are set"

check_secret_length MODELIONN_SECRET_KEY 32
check_secret_length NEXTAUTH_SECRET 32
check_secret_length POSTGRES_PASSWORD 16
check_secret_length REDIS_PASSWORD 16
check_secret_length FLOWER_PASSWORD 12
check_not_default_secret MODELIONN_SECRET_KEY
check_not_default_secret NEXTAUTH_SECRET
pass "Secret strength checks passed"

if grep -qE '(^|\s)-\s*"?5001:5001"?' "$PROD_COMPOSE"; then
  fail "IPFS API port 5001 appears publicly exposed in $PROD_COMPOSE"
fi
pass "IPFS API is not publicly exposed in production compose override"

if ! docker compose \
  -f "$BASE_COMPOSE" \
  -f "$PROD_COMPOSE" \
  --env-file "$ENV_FILE" \
  config >/dev/null; then
  fail "docker compose config validation failed"
fi
pass "Compose configuration validates successfully"

if [[ "${CORS_ORIGINS}" == "*" ]]; then
  warn "CORS_ORIGINS is wildcard; this is not recommended for production"
fi

if [[ "${NEXTAUTH_URL}" == http://* ]]; then
  warn "NEXTAUTH_URL is http://; use https:// in production"
fi

echo "==> Preflight passed. Safe to start production stack."
