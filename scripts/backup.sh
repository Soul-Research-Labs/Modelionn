#!/usr/bin/env bash
set -euo pipefail

# ── Modelionn backup script ─────────────────────────────────
# Usage:
#   ./scripts/backup.sh                   # backup to ./backups/
#   ./scripts/backup.sh /path/to/dir      # backup to custom dir
#   COMPOSE_FILE=docker-compose.prod.yml ./scripts/backup.sh

BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

mkdir -p "$BACKUP_DIR"

echo "==> Modelionn backup — $TIMESTAMP"

# --- PostgreSQL (production) ---
if docker compose -f "$COMPOSE_FILE" ps postgres 2>/dev/null | grep -q running; then
  echo "  Backing up PostgreSQL..."
  docker compose -f "$COMPOSE_FILE" exec -T postgres \
    pg_dump -U modelionn -Fc modelionn \
    > "$BACKUP_DIR/pg_${TIMESTAMP}.dump"
  echo "  ✓ PostgreSQL → $BACKUP_DIR/pg_${TIMESTAMP}.dump"
fi

# --- SQLite (development) ---
if [ -f data/modelionn.db ]; then
  echo "  Backing up SQLite..."
  sqlite3 data/modelionn.db ".backup '$BACKUP_DIR/sqlite_${TIMESTAMP}.db'"
  echo "  ✓ SQLite → $BACKUP_DIR/sqlite_${TIMESTAMP}.db"
fi

# --- Redis ---
if docker compose -f "$COMPOSE_FILE" ps redis 2>/dev/null | grep -q running; then
  echo "  Backing up Redis..."
  docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli BGSAVE >/dev/null
  sleep 2
  docker compose -f "$COMPOSE_FILE" cp redis:/data/dump.rdb "$BACKUP_DIR/redis_${TIMESTAMP}.rdb" 2>/dev/null || true
  echo "  ✓ Redis → $BACKUP_DIR/redis_${TIMESTAMP}.rdb"
fi

# --- Prune old backups (keep last 7) ---
echo "  Pruning backups older than 7 days..."
find "$BACKUP_DIR" -name "pg_*.dump" -mtime +7 -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "sqlite_*.db" -mtime +7 -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "redis_*.rdb" -mtime +7 -delete 2>/dev/null || true

echo "==> Backup complete."
