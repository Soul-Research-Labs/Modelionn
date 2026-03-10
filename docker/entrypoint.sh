#!/bin/sh
set -e

# Validate required environment variables
: "${MODELIONN_DATABASE_URL:?MODELIONN_DATABASE_URL must be set}"

# Optional validation for production
if [ "${MODELIONN_ENV:-development}" = "production" ]; then
  : "${MODELIONN_REDIS_URL:?MODELIONN_REDIS_URL must be set in production}"
  : "${NEXTAUTH_SECRET:?NEXTAUTH_SECRET must be set in production}"
fi

exec "$@"
