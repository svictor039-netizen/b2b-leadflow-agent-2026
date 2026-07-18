#!/usr/bin/env bash
# Verify backup by restoring into a temporary test database, then drop it.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKUP_FILE="${1:-}"
VERIFY_DB="${VERIFY_DB:-leadflow_backup_verify}"
POSTGRES_USER="${POSTGRES_USER:-leadflow}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml}"

if [[ -z "$BACKUP_FILE" || ! -s "$BACKUP_FILE" ]]; then
  echo "Usage: verify_backup.sh <backup.dump>" >&2
  exit 1
fi

if [[ ! "$VERIFY_DB" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
  echo "ERROR: invalid verify database name." >&2
  exit 1
fi

"$ROOT_DIR/scripts/restore_postgres.sh" --target-db "$VERIFY_DB" --i-understand yes "$BACKUP_FILE"

docker compose $COMPOSE_FILES exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 <<SQL
DROP DATABASE IF EXISTS "${VERIFY_DB}";
SQL

echo "Backup verification OK — restored and dropped temporary database '$VERIFY_DB'"
