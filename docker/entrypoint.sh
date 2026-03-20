#!/bin/sh
set -e

# Validate required environment variables
: "${ZKML_DATABASE_URL:?ZKML_DATABASE_URL must be set}"

# Optional validation for production
if [ "${ZKML_ENV:-development}" = "production" ]; then
  : "${ZKML_REDIS_URL:?ZKML_REDIS_URL must be set in production}"
  : "${ZKML_SECRET_KEY:?ZKML_SECRET_KEY must be set in production}"
  : "${NEXTAUTH_SECRET:?NEXTAUTH_SECRET must be set in production}"
  : "${FLOWER_PASSWORD:?FLOWER_PASSWORD must be set in production (Celery Flower dashboard)}"
fi

# Graceful shutdown handler
_term() {
  echo "Caught SIGTERM/SIGINT block!"
  if [ -n "$CHILD_PID" ]; then
    kill -TERM "$CHILD_PID" 2>/dev/null
    wait "$CHILD_PID"
  fi
  exit 0
}

trap _term SIGTERM SIGINT

# Default CORS handling validation
if [ "${ZKML_ENV:-development}" = "production" ]; then
  if echo "$CORS_ORIGINS" | grep -q 'http://'; then
    echo "ERROR: CORS_ORIGINS must not contain http:// in production!"
    exit 1
  fi
fi

# Run the command in background to catch signals
"$@" &
CHILD_PID=$!
wait "$CHILD_PID"
