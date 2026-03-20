#!/usr/bin/env bash
set -euo pipefail

# ── ZKML restore script ────────────────────────────────
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

# --- Verify checksum if available ---
if [ -f "${BACKUP_FILE}.sha256" ]; then
  echo "  Verifying backup integrity..."
  if ! shasum -a 256 -c "${BACKUP_FILE}.sha256" --status 2>/dev/null; then
    echo "Error: Backup checksum verification failed! File may be corrupted or tampered with."
    exit 1
  fi
  echo "  ✓ Checksum verified."
else
  echo "  Warning: No checksum file found (${BACKUP_FILE}.sha256). Proceeding without integrity verification."
fi

echo "==> ZKML restore — $TYPE from $BACKUP_FILE"

case "$TYPE" in
  pg)
    echo "  Restoring PostgreSQL..."
    docker compose -f "$COMPOSE_FILE" exec -T postgres \
      pg_restore -U zkml -d zkml --clean --if-exists -Fc < "$BACKUP_FILE"
    echo "  ✓ PostgreSQL restored."
    ;;
  sqlite)
    echo "  Restoring SQLite..."
    cp "$BACKUP_FILE" data/zkml.db
    echo "  ✓ SQLite restored to data/zkml.db"
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
