#!/usr/bin/env bash
set -euo pipefail

# ── Modelionn restore script ────────────────────────────────
# Usage:
#   ./scripts/restore.sh pg backups/pg_20260315_120000.dump
#   ./scripts/restore.sh sqlite backups/sqlite_20260315_120000.db
#   ./scripts/restore.sh redis backups/redis_20260315_120000.rdb

TYPE="${1:?Usage: restore.sh <pg|sqlite|redis> <backup_file>}"
BACKUP_FILE="${2:?Please provide the backup file path}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "Error: Backup file not found: $BACKUP_FILE"
  exit 1
fi

echo "==> Modelionn restore — $TYPE from $BACKUP_FILE"

case "$TYPE" in
  pg)
    echo "  Restoring PostgreSQL..."
    docker compose -f "$COMPOSE_FILE" exec -T postgres \
      pg_restore -U modelionn -d modelionn --clean --if-exists -Fc < "$BACKUP_FILE"
    echo "  ✓ PostgreSQL restored."
    ;;
  sqlite)
    echo "  Restoring SQLite..."
    cp "$BACKUP_FILE" data/modelionn.db
    echo "  ✓ SQLite restored to data/modelionn.db"
    ;;
  redis)
    echo "  Restoring Redis..."
    docker compose -f "$COMPOSE_FILE" stop redis
    docker compose -f "$COMPOSE_FILE" cp "$BACKUP_FILE" redis:/data/dump.rdb
    docker compose -f "$COMPOSE_FILE" start redis
    echo "  ✓ Redis restored."
    ;;
  *)
    echo "Unknown type: $TYPE. Use: pg, sqlite, or redis"
    exit 1
    ;;
esac

echo "==> Restore complete."
